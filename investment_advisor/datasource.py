"""銘柄データの取得層。

優先順位:
  1. ローカルキャッシュ（既定 24 時間有効。`--refresh` または期限切れで無視）
  2. yfinance によるライブ取得（無料・APIキー不要。最新の株価/財務を取得）
  3. 同梱スナップショット（オフライン/取得失敗時のフォールバック。値は概算）

取得した各銘柄は scoring.py が期待する共通スキーマの dict に正規化します。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

_PKG_DIR = Path(__file__).resolve().parent
_SNAPSHOT_PATH = _PKG_DIR / "snapshot.json"
_CACHE_DIR = _PKG_DIR.parent / ".cache"
_CACHE_PATH = _CACHE_DIR / "latest.json"

# 共通スキーマのキー
METRIC_KEYS = [
    "ticker", "name", "sector", "currency", "price", "market_cap",
    "trailing_pe", "forward_pe", "price_to_book", "roe", "profit_margin",
    "revenue_growth", "earnings_growth", "debt_to_equity", "current_ratio",
    "dividend_yield", "fcf_yield", "return_1y", "beta",
]


class DataResult:
    """取得結果とその出所（live/cache/snapshot）を保持。"""

    def __init__(self, stocks: List[Dict], source: str, as_of: str, note: str = ""):
        self.stocks = stocks
        self.source = source      # "live" | "cache" | "snapshot"
        self.as_of = as_of        # 取得時刻や基準日
        self.note = note


# ---------------------------------------------------------------------------
# スナップショット（フォールバック）
# ---------------------------------------------------------------------------
def load_snapshot(tickers: Optional[List[str]] = None) -> DataResult:
    data = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    stocks = data["stocks"]
    if tickers:
        wanted = {t.upper() for t in tickers}
        stocks = [s for s in stocks if s["ticker"].upper() in wanted]
    return DataResult(
        stocks=stocks,
        source="snapshot",
        as_of=data.get("as_of", "unknown"),
        note="同梱スナップショット（概算・最新ではない可能性あり）を使用しました。",
    )


# ---------------------------------------------------------------------------
# キャッシュ
# ---------------------------------------------------------------------------
def _read_cache(tickers: List[str], max_age_h: float) -> Optional[DataResult]:
    if not _CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    age_h = (time.time() - data.get("fetched_at", 0)) / 3600.0
    if age_h > max_age_h:
        return None
    cached = {s["ticker"].upper(): s for s in data.get("stocks", [])}
    if not all(t.upper() in cached for t in tickers):
        return None  # 要求銘柄が揃っていなければ作り直す
    stocks = [cached[t.upper()] for t in tickers]
    return DataResult(
        stocks=stocks,
        source="cache",
        as_of=data.get("as_of", "unknown"),
        note=f"ローカルキャッシュ（約{age_h:.1f}時間前に取得）を使用しました。",
    )


def _write_cache(stocks: List[Dict], as_of: str) -> None:
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps({"fetched_at": time.time(), "as_of": as_of, "stocks": stocks},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # キャッシュ書き込み失敗は致命的ではない


# ---------------------------------------------------------------------------
# ライブ取得（yfinance）
# ---------------------------------------------------------------------------
def _normalize_dividend_yield(raw) -> Optional[float]:
    """yfinance の dividendYield は版により % か小数。0.5 を境に判定して小数へ。"""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1.0:          # 例: 3.1 → 3.1%
        return v / 100.0
    return v


def _fetch_one(tk, ticker: str) -> Optional[Dict]:
    import math
    info = tk.info or {}
    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # 取得失敗（存在しない/データ無し）
        return None

    # 過去1年リターンを終値から計算
    return_1y = None
    try:
        hist = tk.history(period="1y", interval="1d")
        closes = hist.get("Close")
        if closes is not None and len(closes) >= 2:
            first, last = float(closes.iloc[0]), float(closes.iloc[-1])
            if first > 0:
                return_1y = last / first - 1.0
    except Exception:
        pass

    # FCF利回り = フリーキャッシュフロー / 時価総額
    fcf_yield = None
    fcf = info.get("freeCashflow")
    mcap = info.get("marketCap")
    if fcf and mcap and mcap > 0:
        fcf_yield = fcf / mcap

    de = info.get("debtToEquity")  # yfinance は % 表記（例 150.0）

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector") or "—",
        "currency": info.get("currency") or "USD",
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": mcap,
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),
        "profit_margin": info.get("profitMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "debt_to_equity": de,
        "current_ratio": info.get("currentRatio"),
        "dividend_yield": _normalize_dividend_yield(info.get("dividendYield")),
        "fcf_yield": fcf_yield,
        "return_1y": return_1y,
        "beta": info.get("beta"),
    }


def fetch_live(tickers: List[str]) -> Optional[DataResult]:
    """yfinance でライブ取得。ライブラリ未導入や全件失敗なら None。"""
    try:
        import yfinance as yf
    except ImportError:
        return None

    stocks: List[Dict] = []
    for t in tickers:
        try:
            data = _fetch_one(yf.Ticker(t), t)
        except Exception:
            data = None
        if data:
            stocks.append(data)

    if not stocks:
        return None

    as_of = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    note = f"yfinance でライブ取得しました（{len(stocks)}/{len(tickers)} 銘柄）。"
    if len(stocks) < len(tickers):
        failed = [t for t in tickers if t.upper() not in {s["ticker"].upper() for s in stocks}]
        note += f" 取得できなかった銘柄: {', '.join(failed)}"
    return DataResult(stocks=stocks, source="live", as_of=as_of, note=note)


# ---------------------------------------------------------------------------
# 統合エントリ
# ---------------------------------------------------------------------------
def get_data(tickers: List[str], *, offline: bool = False, refresh: bool = False,
             cache_max_age_h: float = 24.0) -> DataResult:
    """データ取得の統合関数。出所は DataResult.source で判別できる。"""
    if offline:
        return load_snapshot(tickers)

    if not refresh:
        cached = _read_cache(tickers, cache_max_age_h)
        if cached:
            return cached

    live = fetch_live(tickers)
    if live:
        _write_cache(live.stocks, live.as_of)
        return live

    # 最後の手段: スナップショット
    snap = load_snapshot(tickers)
    snap.note = "ライブ取得に失敗したため、" + snap.note
    return snap
