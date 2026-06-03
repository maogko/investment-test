#!/usr/bin/env python3
"""初心者向け 長期投資スクリーニングツール（CLI）。

使い方の例:
    python advisor.py                         # 既定ユニバースをバランス型で診断
    python advisor.py --profile conservative  # 安定重視で診断
    python advisor.py --tickers AAPL MSFT 7203.T --top 3
    python advisor.py --amount 1000000        # 100万円を上位銘柄に配分提案
    python advisor.py --offline               # ネット不要（同梱データ）
    python advisor.py --json                  # 機械可読なJSON出力

注意: 本ツールは情報提供・学習目的の参考であり、投資勧誘や個別の投資助言
ではありません。最終的な投資判断はご自身の責任で行ってください。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from investment_advisor import datasource
from investment_advisor.scoring import (
    FACTOR_LABELS_JA,
    PROFILE_LABELS_JA,
    PROFILES,
    rank_stocks,
)
from investment_advisor.universe import DEFAULT_UNIVERSE

DISCLAIMER = (
    "※ 本ツールは情報提供・学習目的の参考情報です。投資勧誘や個別銘柄の"
    "投資助言ではなく、将来の成果を保証するものでもありません。\n"
    "  投資は元本割れのリスクを伴います。最終的な判断はご自身の責任で、"
    "余裕資金・分散・長期の積立を基本に行ってください。"
)


def _bar(score: float, width: int = 20) -> str:
    filled = int(round(score / 100.0 * width))
    return "█" * filled + "░" * (width - filled)


def _grade(total: float) -> str:
    if total >= 75:
        return "A（長期保有の有力候補）"
    if total >= 65:
        return "B（候補。要点を確認のうえ検討）"
    if total >= 55:
        return "C（中立。他候補と比較を）"
    return "D（現時点では見送り寄り）"


def build_report(scored, profile: str, top: int, amount: float | None,
                 result: datasource.DataResult) -> str:
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("  初心者向け 長期投資スクリーニング（3年以上の保有を想定）")
    lines.append("=" * 64)
    lines.append(f"リスク許容度プロファイル : {PROFILE_LABELS_JA[profile]}（{profile}）")
    lines.append(f"データの出所             : {result.source}（基準: {result.as_of}）")
    lines.append(f"対象銘柄数               : {len(scored)} 銘柄中 上位 {min(top, len(scored))} 件を表示")
    if result.note:
        lines.append(f"備考                     : {result.note}")
    lines.append("")

    picks = scored[:top]
    for i, s in enumerate(picks, 1):
        lines.append("-" * 64)
        lines.append(f"#{i}  {s.name}  [{s.ticker}]  — {s.sector}")
        lines.append(f"    総合スコア {s.total:5.1f}/100  {_bar(s.total)}  判定: {_grade(s.total)}")
        price = s.metrics.get("price")
        if price is not None:
            lines.append(f"    参考株価   {price:,.2f} {s.currency}")
        # ファクター内訳
        fac = "  ".join(
            f"{FACTOR_LABELS_JA[k]}:{s.factors[k]:>4.0f}" for k in
            ["quality", "health", "growth", "value", "stability", "momentum"]
        )
        lines.append(f"    内訳: {fac}")
        lines.append("    ◎ 推奨理由:")
        for r in s.reasons:
            lines.append(f"        ・{r}")
        if s.cautions:
            lines.append("    △ 注意点:")
            for c in s.cautions:
                lines.append(f"        ・{c}")
        if s.missing:
            lines.append(f"    ＊ データ欠損（中立扱い）: {', '.join(s.missing)}")
        lines.append("")

    # 配分提案（任意）
    if amount and picks:
        lines.append("=" * 64)
        lines.append(f"  参考: {amount:,.0f} の配分イメージ（スコア加重・分散の出発点）")
        lines.append("=" * 64)
        weights = _score_weights([s.total for s in picks])
        for s, w in zip(picks, weights):
            lines.append(f"    {s.name:<22} [{s.ticker:<6}]  {w*100:5.1f}%   {amount*w:,.0f}")
        lines.append("    ※ 実際には複数セクターへの分散と、時間分散（積立）を推奨します。")
        lines.append("")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _score_weights(scores: List[float]) -> List[float]:
    """スコアの2乗で加重し、合計1.0に正規化（上位ほど厚く、ただし極端化しない）。"""
    adj = [max(s, 1.0) ** 2 for s in scores]
    total = sum(adj)
    return [a / total for a in adj]


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="最新データに基づく初心者向け長期投資スクリーニング",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tickers", nargs="+", metavar="TICKER",
                   help="対象ティッカー（例: AAPL MSFT 7203.T）。未指定なら既定ユニバース")
    p.add_argument("--profile", choices=list(PROFILES), default="balanced",
                   help="リスク許容度（既定: balanced）")
    p.add_argument("--top", type=int, default=5, help="表示する上位件数（既定: 5）")
    p.add_argument("--amount", type=float, default=None,
                   help="この金額を上位銘柄に配分する参考イメージを表示")
    p.add_argument("--offline", action="store_true",
                   help="ネット接続せず同梱スナップショットのみ使用")
    p.add_argument("--refresh", action="store_true",
                   help="キャッシュを無視して最新データを取り直す")
    p.add_argument("--cache-hours", type=float, default=24.0,
                   help="キャッシュ有効時間（時間, 既定: 24）")
    p.add_argument("--json", action="store_true", help="JSON形式で出力")
    args = p.parse_args(argv)

    tickers = [t.upper() for t in (args.tickers or DEFAULT_UNIVERSE)]

    result = datasource.get_data(
        tickers, offline=args.offline, refresh=args.refresh,
        cache_max_age_h=args.cache_hours,
    )
    if not result.stocks:
        print("対象データを取得できませんでした。", file=sys.stderr)
        return 1

    scored = rank_stocks(result.stocks, args.profile)

    if args.json:
        out = {
            "profile": args.profile,
            "source": result.source,
            "as_of": result.as_of,
            "note": result.note,
            "results": [
                {
                    "rank": i + 1,
                    "ticker": s.ticker,
                    "name": s.name,
                    "sector": s.sector,
                    "total_score": s.total,
                    "factors": s.factors,
                    "reasons": s.reasons,
                    "cautions": s.cautions,
                    "missing": s.missing,
                }
                for i, s in enumerate(scored[:args.top])
            ],
            "disclaimer": DISCLAIMER,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(build_report(scored, args.profile, args.top, args.amount, result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
