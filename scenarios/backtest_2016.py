#!/usr/bin/env python3
"""フェアな後方検証（ウォークフォワード）:
『2016年のデータだけ』でツールに銘柄を選ばせ、その推奨を2016→2026で
保有したら今いくらになっていたか、を再現する。

前回の backtest.py は「現在の推奨銘柄」を過去に当てはめるため後知恵
バイアスを含んでいた。本スクリプトは入力を2016年時点のファンダメンタルズ
（scenarios/snapshot_2016.json）に限定し、当時の情報だけで選定する。

注意:
  - 2016年のファンダメンタルズ、および2016/2026の株価はいずれも概算の
    参考値（調整後・株式分割反映）。正確な数値はご自身で再取得を推奨。
  - 2026年6月はAI relヴァリュエーションが高い局面で、出遅れ株も上振れ
    している点に留意（中央値も併記）。
  - 過去の実績は将来を保証しない。
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # リポジトリ直下を import パスに追加

from investment_advisor.scoring import rank_stocks  # noqa: E402

# 2026年6月時点の株価（USD, 概算）。snapshot_2016.json の "price" は
# 2016年の分割調整後株価なので、両者の比でトータルの値上がり倍率を出す。
PRICE_2026 = {
    # ツールが2016年データで選んだ上位
    "META": 600.10, "NVDA": 221.79, "JNJ": 222.89, "CSCO": 128.28,
    "GOOGL": 364.03, "INTC": 106.14, "V": 317.32, "ORCL": 241.85,
    "AAPL": 314.70, "QCOM": 240.84,
    # ツールが避けた“割安トラップ”系（対比用）
    "IBM": 324.00, "XOM": 150.54, "T": 24.55, "WFC": 77.10,
    "MSFT": 441.31, "AMZN": 230.00, "BRK-B": 471.43, "KO": 70.00,
    "PG": 165.00, "WMT": 98.00, "PFE": 25.00, "VZ": 44.00,
    "DIS": 115.00, "MCD": 277.19, "HD": 410.00,
}

SP500_MULTIPLE = 3.3  # 2016→2026 のおおよその指数リターン（参考）


def _multiple(ticker: str, price_2016: float):
    p1 = PRICE_2026.get(ticker)
    if p1 is None or not price_2016:
        return None
    return p1 / price_2016


def main(top: int = 10, profile: str = "balanced", amount: float = 1_000_000) -> int:
    data = json.loads((_HERE / "snapshot_2016.json").read_text(encoding="utf-8"))
    by_ticker = {s["ticker"]: s for s in data["stocks"]}
    ranked = rank_stocks(data["stocks"], profile)
    picks = ranked[:top]

    print("=" * 64)
    print(f"  2016年のデータだけで選んだ推奨{top}銘柄 → 2016〜2026 の結果")
    print(f"  プロファイル: {profile} / 基準: {data['as_of']}")
    print("=" * 64)
    print(f"{'銘柄':<7}{'2016':>9}{'2026':>9}{'倍率':>8}{'年率':>8}")
    print("-" * 64)
    mults = []
    for s in picks:
        p0 = by_ticker[s.ticker]["price"]
        m = _multiple(s.ticker, p0)
        if m is None:
            print(f"{s.ticker:<7}  (2026株価データ未登録)")
            continue
        mults.append(m)
        cagr = (m ** (1 / 10) - 1) * 100
        print(f"{s.ticker:<7}{p0:>9.2f}{PRICE_2026[s.ticker]:>9.2f}{m:>7.1f}x{cagr:>7.1f}%")
    print("-" * 64)

    avg = sum(mults) / len(mults)
    med = statistics.median(mults)
    beat = sum(1 for m in mults if m > SP500_MULTIPLE)
    print(f"等金額ポートフォリオ平均 : {avg:>6.1f}x（年率 {(avg**(1/10)-1)*100:.1f}%）")
    print(f"中央値（典型的な1銘柄）  : {med:>6.1f}x（年率 {(med**(1/10)-1)*100:.1f}%）")
    print(f"S&P500（{SP500_MULTIPLE}x）を上回った銘柄: {beat}/{len(mults)}")
    print(f"{amount:,.0f}円 → 等金額で約 {amount*avg:,.0f}円 / 中央値で約 {amount*med:,.0f}円")

    # ツールが避けた“割安トラップ”との対比
    print("\n" + "-" * 64)
    print("参考: ツールが下位評価して避けた“2016年に割安に見えた”銘柄")
    print("-" * 64)
    for t in ["T", "WFC", "XOM", "IBM"]:
        if t in by_ticker:
            p0 = by_ticker[t]["price"]
            m = _multiple(t, p0)
            print(f"{t:<7}{p0:>9.2f}{PRICE_2026[t]:>9.2f}{m:>7.1f}x"
                  f"{'  ← 市場平均割れ' if m < SP500_MULTIPLE else ''}")

    print("\n※ 概算値・後方検証であり将来を保証しません。"
          "平均はNVDA等の大化けに強く影響されるため中央値も重視してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
