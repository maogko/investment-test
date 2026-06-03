#!/usr/bin/env python3
"""推奨銘柄の過去リターンを検証するバックテスト（ヒストリカル）。

「もし N 年前にこの推奨銘柄を等金額で買い、保有し続けていたら？」を、
yfinance の調整後株価（株式分割・配当を反映）で計算します。

使い方:
    python backtest.py                       # 既定ユニバースを10年で検証
    python backtest.py --years 10 --amount 1000000
    python backtest.py --tickers NVDA MSFT GOOGL --years 5

⚠️ 重要な注意（必ずお読みください）:
  - 本スクリプトは「現在の」推奨銘柄を過去に当てはめます。これは結果を
    知ったうえで選んだ銘柄であり、**後知恵・生存者バイアス**を含みます。
    （10年前に実際にツールを動かせば、2016年当時のデータで別の銘柄を
    推奨していたはずです。）したがって下記の数字は「この銘柄群が結果的に
    どれだけ伸びたか」であって、ツールの将来予測能力ではありません。
  - 過去の実績は将来を保証しません。
  - ネット接続と yfinance が必要です（`pip install -r requirements.txt`）。
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from investment_advisor.universe import DEFAULT_UNIVERSE


def _total_return(ticker: str, years: int) -> Optional[dict]:
    """調整後終値で N 年リターンを計算。取得失敗時 None。"""
    import yfinance as yf

    try:
        # auto_adjust=True で分割・配当を反映した調整後終値を取得
        hist = yf.Ticker(ticker).history(period=f"{years}y", interval="1mo",
                                          auto_adjust=True)
    except Exception:
        return None
    closes = hist.get("Close") if hist is not None else None
    if closes is None or len(closes) < 2:
        return None
    start = float(closes.iloc[0])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    span_years = max((closes.index[-1] - closes.index[0]).days / 365.25, 0.1)
    multiple = end / start
    total_pct = (multiple - 1.0) * 100.0
    cagr = (multiple ** (1.0 / span_years) - 1.0) * 100.0
    return {
        "ticker": ticker,
        "start": start,
        "end": end,
        "span_years": span_years,
        "multiple": multiple,
        "total_pct": total_pct,
        "cagr": cagr,
    }


def run(tickers: List[str], years: int, amount: Optional[float]) -> int:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        print("yfinance が未導入です。`pip install -r requirements.txt` を実行してください。",
              file=sys.stderr)
        return 2

    rows = []
    for t in tickers:
        r = _total_return(t, years)
        if r:
            rows.append(r)
        else:
            print(f"  ! {t}: データ取得に失敗（スキップ）", file=sys.stderr)

    if not rows:
        print("ヒストリカルデータを取得できませんでした（ネット接続を確認してください）。",
              file=sys.stderr)
        return 1

    rows.sort(key=lambda r: r["multiple"], reverse=True)

    print("=" * 72)
    print(f"  バックテスト: 約{years}年保有した場合のリターン（分割・配当調整後）")
    print("=" * 72)
    print(f"{'銘柄':<8}{'起点':>10}{'現在':>10}{'倍率':>9}{'累計':>10}{'年率':>9}")
    print("-" * 72)
    for r in rows:
        print(f"{r['ticker']:<8}{r['start']:>10.2f}{r['end']:>10.2f}"
              f"{r['multiple']:>8.1f}x{r['total_pct']:>9.0f}%{r['cagr']:>8.1f}%")
    print("-" * 72)

    # 等金額ポートフォリオ（各銘柄に同額投資）
    avg_mult = sum(r["multiple"] for r in rows) / len(rows)
    sorted_mult = sorted(r["multiple"] for r in rows)
    n = len(sorted_mult)
    median_mult = (sorted_mult[n // 2] if n % 2 else
                   (sorted_mult[n // 2 - 1] + sorted_mult[n // 2]) / 2)
    print(f"等金額ポートフォリオ平均倍率 : {avg_mult:>6.1f}x（累計 {(avg_mult-1)*100:.0f}%）")
    print(f"中央値（典型的な1銘柄）      : {median_mult:>6.1f}x（累計 {(median_mult-1)*100:.0f}%）")
    if amount:
        print(f"{amount:,.0f} を等金額投資 → 現在価値 約 {amount*avg_mult:,.0f}"
              f"（中央値ベースなら 約 {amount*median_mult:,.0f}）")
    print("-" * 72)
    print("※ 現在の推奨銘柄を過去に当てはめた後知恵バイアスを含みます。"
          "平均は少数の大化け銘柄に強く影響されるため、中央値も併記しています。")
    print("※ 過去の実績は将来を保証しません。")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="推奨銘柄の過去リターンを検証するバックテスト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tickers", nargs="+", metavar="TICKER",
                   help="対象ティッカー（未指定なら既定ユニバース）")
    p.add_argument("--years", type=int, default=10, help="保有年数（既定: 10）")
    p.add_argument("--amount", type=float, default=None, help="投資金額（現在価値を試算）")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in (args.tickers or DEFAULT_UNIVERSE)]
    return run(tickers, args.years, args.amount)


if __name__ == "__main__":
    raise SystemExit(main())
