"""scoring / datasource の基本動作テスト（標準ライブラリの unittest のみ使用）。

実行: python -m unittest discover -s tests -v
"""

import unittest

from investment_advisor import datasource
from investment_advisor.scoring import (
    PROFILES,
    _higher_better,
    _lower_better,
    rank_stocks,
    score_stock,
)


# 健全な優良企業の例（高スコアを期待）
GOOD = {
    "ticker": "GOOD", "name": "Good Co", "sector": "Tech", "currency": "USD",
    "price": 100.0, "market_cap": 800_000_000_000,
    "trailing_pe": 18.0, "forward_pe": 16.0, "price_to_book": 4.0,
    "roe": 0.30, "profit_margin": 0.28, "revenue_growth": 0.18,
    "earnings_growth": 0.22, "debt_to_equity": 30.0, "current_ratio": 2.0,
    "dividend_yield": 0.02, "fcf_yield": 0.05, "return_1y": 0.25, "beta": 0.9,
}

# 割高・低成長・高負債・赤字の例（低スコアを期待）
WEAK = {
    "ticker": "WEAK", "name": "Weak Co", "sector": "Misc", "currency": "USD",
    "price": 50.0, "market_cap": 2_000_000_000,
    "trailing_pe": -5.0, "forward_pe": 80.0, "price_to_book": 20.0,
    "roe": 0.02, "profit_margin": 0.01, "revenue_growth": -0.05,
    "earnings_growth": -0.20, "debt_to_equity": 300.0, "current_ratio": 0.5,
    "dividend_yield": 0.0, "fcf_yield": -0.02, "return_1y": -0.30, "beta": 2.2,
}


class NormalizationTest(unittest.TestCase):
    def test_higher_better_bounds(self):
        self.assertEqual(_higher_better(0.30, 0.05, 0.30), 100.0)
        self.assertEqual(_higher_better(0.05, 0.05, 0.30), 0.0)
        self.assertEqual(_higher_better(None, 0, 1), None)

    def test_lower_better_bounds(self):
        self.assertEqual(_lower_better(0.0, 0.0, 200.0), 100.0)
        self.assertEqual(_lower_better(200.0, 0.0, 200.0), 0.0)
        self.assertAlmostEqual(_lower_better(100.0, 0.0, 200.0), 50.0)


class ScoringTest(unittest.TestCase):
    def test_good_beats_weak(self):
        good = score_stock(GOOD, "balanced")
        weak = score_stock(WEAK, "balanced")
        self.assertGreater(good.total, weak.total)
        self.assertGreater(good.total, 60)
        self.assertLess(weak.total, 45)

    def test_reasons_and_cautions_generated(self):
        good = score_stock(GOOD, "balanced")
        self.assertTrue(good.reasons)
        weak = score_stock(WEAK, "balanced")
        self.assertTrue(weak.cautions)  # 弱点があるので注意点が出る

    def test_negative_pe_scores_zero_value(self):
        weak = score_stock(WEAK, "balanced")
        # 赤字なので割安度は低い
        self.assertLess(weak.factors["value"], 40)

    def test_profiles_change_ranking_weights(self):
        # aggressive は growth 重み大 → 成長株がより高評価になる方向
        cons = score_stock(GOOD, "conservative").total
        aggr = score_stock(GOOD, "aggressive").total
        self.assertNotEqual(cons, aggr)

    def test_missing_data_is_neutral(self):
        partial = dict(GOOD)
        partial["roe"] = None
        partial["beta"] = None
        s = score_stock(partial, "balanced")
        self.assertIn("ROE", s.missing)
        self.assertIn("ベータ", s.missing)
        # 欠損があってもクラッシュせずスコアが出る
        self.assertGreater(s.total, 0)

    def test_rank_sorts_descending(self):
        ranked = rank_stocks([WEAK, GOOD], "balanced")
        self.assertEqual(ranked[0].ticker, "GOOD")
        self.assertEqual(ranked[1].ticker, "WEAK")

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            rank_stocks([GOOD], "nope")


class SnapshotTest(unittest.TestCase):
    def test_snapshot_loads_and_scores(self):
        result = datasource.load_snapshot()
        self.assertGreater(len(result.stocks), 5)
        ranked = rank_stocks(result.stocks, "balanced")
        self.assertEqual(len(ranked), len(result.stocks))
        # すべての銘柄に必須キーがある
        for s in result.stocks:
            for key in ("ticker", "name", "sector"):
                self.assertIn(key, s)

    def test_snapshot_ticker_filter(self):
        result = datasource.load_snapshot(["AAPL", "MSFT"])
        tickers = {s["ticker"] for s in result.stocks}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_offline_get_data(self):
        result = datasource.get_data(["AAPL"], offline=True)
        self.assertEqual(result.source, "snapshot")
        self.assertTrue(result.stocks)

    def test_all_profiles_valid_weights(self):
        for name, w in PROFILES.items():
            self.assertAlmostEqual(sum(w.values()), 1.0, places=6,
                                   msg=f"{name} の重み合計が1.0でない")


if __name__ == "__main__":
    unittest.main()
