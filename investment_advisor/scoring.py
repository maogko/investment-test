"""長期保有（3年以上）を前提とした銘柄スコアリングと推奨理由の生成。

考え方
------
1銘柄を 6 つのファクターで 0〜100 点に正規化し、リスク許容度プロファイル
ごとの重み付けで総合スコア（0〜100）を出します。

- quality   収益性・資本効率  : ROE, 利益率
- health    財務健全性        : 負債比率, 流動比率, FCF利回り
- growth    成長性            : 売上成長率, 利益成長率
- value     割安度            : PER, PBR
- stability 安定性            : ベータ, 配当, 時価総額
- momentum  勢い              : 過去1年リターン

各ファクターは「長期で報われやすい特性」を高得点に寄せています。
データが欠損している指標は中立（50点）として扱い、理由文に注記します。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# リスク許容度プロファイル（ファクター重み・合計1.0）
# ---------------------------------------------------------------------------
PROFILES: Dict[str, Dict[str, float]] = {
    # 安定重視: 財務健全性・安定性・割安度を重く、成長/勢いは軽く
    "conservative": {
        "quality": 0.20, "health": 0.26, "growth": 0.08,
        "value": 0.18, "stability": 0.22, "momentum": 0.06,
    },
    # バランス型（初心者の既定）
    "balanced": {
        "quality": 0.22, "health": 0.20, "growth": 0.18,
        "value": 0.18, "stability": 0.12, "momentum": 0.10,
    },
    # 成長重視: 成長性・勢いを重く
    "aggressive": {
        "quality": 0.22, "health": 0.12, "growth": 0.30,
        "value": 0.12, "stability": 0.04, "momentum": 0.20,
    },
}

PROFILE_LABELS_JA = {
    "conservative": "安定重視（守り）",
    "balanced": "バランス型",
    "aggressive": "成長重視（攻め）",
}

FACTOR_LABELS_JA = {
    "quality": "収益性",
    "health": "財務健全性",
    "growth": "成長性",
    "value": "割安度",
    "stability": "安定性",
    "momentum": "勢い",
}


@dataclass
class ScoredStock:
    ticker: str
    name: str
    sector: str
    currency: str
    total: float
    factors: Dict[str, float]
    metrics: Dict[str, Optional[float]]
    reasons: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 正規化ヘルパー
# ---------------------------------------------------------------------------
def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _higher_better(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    """大きいほど良い指標を 0〜100 に。value<=lo→0, value>=hi→100。"""
    if value is None:
        return None
    if hi == lo:
        return 50.0
    return _clamp((value - lo) / (hi - lo) * 100.0)


def _lower_better(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    """小さいほど良い指標を 0〜100 に。value<=lo→100, value>=hi→0。"""
    if value is None:
        return None
    if hi == lo:
        return 50.0
    return _clamp(100.0 - (value - lo) / (hi - lo) * 100.0)


def _avg(scores: List[Optional[float]]) -> (float, int):
    """欠損(None)を除いた平均と、欠損数を返す。全欠損なら中立50。"""
    present = [s for s in scores if s is not None]
    missing = len(scores) - len(present)
    if not present:
        return 50.0, missing
    return sum(present) / len(present), missing


# ---------------------------------------------------------------------------
# ファクター別スコア
# ---------------------------------------------------------------------------
def _factor_scores(m: Dict[str, Optional[float]]) -> (Dict[str, float], List[str]):
    missing: List[str] = []

    def track(name: str, score: Optional[float]) -> Optional[float]:
        if score is None:
            missing.append(name)
        return score

    quality, _ = _avg([
        track("ROE", _higher_better(m.get("roe"), 0.05, 0.30)),
        track("利益率", _higher_better(m.get("profit_margin"), 0.02, 0.30)),
    ])
    health, _ = _avg([
        track("負債比率", _lower_better(m.get("debt_to_equity"), 0.0, 200.0)),
        track("流動比率", _higher_better(m.get("current_ratio"), 0.8, 2.5)),
        track("FCF利回り", _higher_better(m.get("fcf_yield"), 0.0, 0.08)),
    ])
    growth, _ = _avg([
        track("売上成長率", _higher_better(m.get("revenue_growth"), 0.0, 0.25)),
        track("利益成長率", _higher_better(m.get("earnings_growth"), 0.0, 0.30)),
    ])
    value, _ = _avg([
        track("PER", _value_pe(m.get("trailing_pe"))),
        track("PBR", _lower_better(m.get("price_to_book"), 1.0, 12.0)),
    ])
    stability, _ = _avg([
        track("ベータ", _lower_better(m.get("beta"), 0.6, 1.8)),
        track("配当利回り", _higher_better(m.get("dividend_yield"), 0.0, 0.04)),
        track("時価総額", _marketcap_score(m.get("market_cap"))),
    ])
    momentum = _higher_better(m.get("return_1y"), -0.20, 0.40)
    if momentum is None:
        missing.append("1年リターン")
        momentum = 50.0

    factors = {
        "quality": round(quality, 1),
        "health": round(health, 1),
        "growth": round(growth, 1),
        "value": round(value, 1),
        "stability": round(stability, 1),
        "momentum": round(momentum, 1),
    }
    return factors, missing


def _value_pe(pe: Optional[float]) -> Optional[float]:
    """PER。赤字(<=0)は割安と見なさず最低点。10倍以下→100, 45倍以上→0。"""
    if pe is None:
        return None
    if pe <= 0:
        return 0.0
    return _lower_better(pe, 10.0, 45.0)


def _marketcap_score(mcap: Optional[float]) -> Optional[float]:
    """時価総額（USD）を対数スケールで安定性に換算。
    10億ドル→0 付近, 5000億ドル以上→100 付近。"""
    if mcap is None or mcap <= 0:
        return None
    log = math.log10(mcap)
    # 1e9 (log=9) → 0, 5e11 (log=11.7) → 100
    return _higher_better(log, 9.0, 11.7)


# ---------------------------------------------------------------------------
# 推奨理由・注意点の生成
# ---------------------------------------------------------------------------
def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _num(x: Optional[float], suffix: str = "") -> str:
    return "—" if x is None else f"{x:.1f}{suffix}"


def _build_narrative(m: Dict[str, Optional[float]], factors: Dict[str, float]
                     ) -> (List[str], List[str]):
    reasons: List[str] = []
    cautions: List[str] = []

    # --- 良い点（スコアが高いファクターを具体的な数値とともに） ---
    if factors["quality"] >= 65:
        reasons.append(
            f"収益性が高い（ROE {_pct(m.get('roe'))} / 純利益率 {_pct(m.get('profit_margin'))}）。"
            "稼ぐ力が強く、長期で利益を積み上げやすい。"
        )
    if factors["health"] >= 65:
        reasons.append(
            f"財務が健全（負債比率 {_num(m.get('debt_to_equity'), '%')} / "
            f"FCF利回り {_pct(m.get('fcf_yield'))}）。不況耐性が高く長期保有向き。"
        )
    if factors["growth"] >= 65:
        reasons.append(
            f"成長が続いている（売上 {_pct(m.get('revenue_growth'))} / "
            f"利益 {_pct(m.get('earnings_growth'))} 成長）。将来の価値増加が期待できる。"
        )
    if factors["value"] >= 65:
        reasons.append(
            f"バリュエーションが過熱していない（PER {_num(m.get('trailing_pe'), '倍')} / "
            f"PBR {_num(m.get('price_to_book'), '倍')}）。割高づかみのリスクが低め。"
        )
    if factors["stability"] >= 65:
        reasons.append(
            f"値動きが安定（ベータ {_num(m.get('beta'))} / 配当利回り {_pct(m.get('dividend_yield'))}）。"
            "初心者でも保有を続けやすい。"
        )
    if factors["momentum"] >= 70:
        reasons.append(
            f"直近の株価が堅調（過去1年 {_pct(m.get('return_1y'))}）。市場の評価が向いている。"
        )

    # --- 注意点（スコアが低いファクター = 弱点・リスク） ---
    if factors["value"] <= 35:
        pe = m.get("trailing_pe")
        if pe is not None and pe <= 0:
            cautions.append("足元は赤字（PERが算出不可）。黒字化の確度を要確認。")
        else:
            cautions.append(
                f"バリュエーションが高め（PER {_num(m.get('trailing_pe'), '倍')} / "
                f"PBR {_num(m.get('price_to_book'), '倍')}）。期待が株価に織り込み済みで、"
                "業績未達だと下落しやすい。"
            )
    if factors["growth"] <= 35:
        cautions.append(
            f"成長は緩やか（売上 {_pct(m.get('revenue_growth'))}）。"
            "大きな値上がりより配当・安定性に期待する銘柄。"
        )
    if factors["health"] <= 35:
        cautions.append(
            f"財務レバレッジが高い（負債比率 {_num(m.get('debt_to_equity'), '%')}）。"
            "金利上昇局面では負担が増える点に注意。"
        )
    if factors["stability"] <= 35:
        cautions.append(
            f"値動きが大きめ（ベータ {_num(m.get('beta'))}）。短期の含み損に動揺しない覚悟が必要。"
        )

    if not reasons:
        reasons.append("際立った強みは少ないが、総合的に大きな弱点もないバランス型。")

    return reasons, cautions


# ---------------------------------------------------------------------------
# 公開API
# ---------------------------------------------------------------------------
def score_stock(metrics: Dict[str, Optional[float]], profile: str) -> ScoredStock:
    weights = PROFILES[profile]
    factors, missing = _factor_scores(metrics)
    total = sum(factors[f] * w for f, w in weights.items())
    reasons, cautions = _build_narrative(metrics, factors)
    return ScoredStock(
        ticker=metrics.get("ticker", "?"),
        name=metrics.get("name") or metrics.get("ticker", "?"),
        sector=metrics.get("sector") or "—",
        currency=metrics.get("currency") or "USD",
        total=round(total, 1),
        factors=factors,
        metrics=metrics,
        reasons=reasons,
        cautions=cautions,
        missing=missing,
    )


def rank_stocks(stocks: List[Dict[str, Optional[float]]], profile: str
                ) -> List[ScoredStock]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile} (choose from {list(PROFILES)})")
    scored = [score_stock(s, profile) for s in stocks]
    scored.sort(key=lambda s: s.total, reverse=True)
    return scored
