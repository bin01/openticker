"""Checks that the numbers OpenTicker shows are computed correctly: RSI, MACD, moving averages, support and
resistance, the trend label, fund contributions and insider summaries. Standard library only.

    openticker test        (or: python -m unittest discover tests)
"""
import datetime as dt
import math
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import agent  # noqa: E402
import levels  # noqa: E402


def bars(closes, spread=0.01, vol=1_000_000, start=dt.date(2025, 1, 2)):
    """Daily bars from closes: highs and lows a fixed % around the close, weekdays only."""
    d, out = start, []
    while len(out) < len(closes):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return {"d": out, "o": list(closes), "h": [c * (1 + spread) for c in closes], "l": [c * (1 - spread) for c in closes],
            "c": list(closes), "v": [vol] * len(closes)}


class FakeServer(types.SimpleNamespace):
    """Just enough of server.py for the sections under test: no network, no price feed."""
    def __init__(self):
        super().__init__(X=types.SimpleNamespace(SECTOR_ETFS=[("XLK", "Technology", "technology")]))

    def extra(self, name, q):
        raise RuntimeError("offline")


class RSI(unittest.TestCase):
    # Wilder's 14-day RSI on the worked example published by StockCharts ("Relative Strength Index", ChartSchool).
    CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
              46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
              43.42, 42.66, 43.13]
    EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
                41.87, 45.46, 37.30, 33.08, 37.77]

    def test_matches_published_example(self):
        r = agent._rsi(self.CLOSES)
        self.assertEqual(len(r), len(self.CLOSES))
        got = [x for x in r if x is not None]
        self.assertEqual(len(got), len(self.EXPECTED))
        # StockCharts rounds its running averages to two decimals, which puts its first values up to 0.07 high;
        # the gap shrinks as the averages settle. An exact calculation follows below.
        for g, e in zip(got, self.EXPECTED):
            self.assertAlmostEqual(g, e, delta=0.1)

    def test_matches_pandas_wilder(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas isn't installed")
        c = pd.Series(self.CLOSES + [43 + (i % 5) * 0.4 for i in range(60)])
        d = c.diff().iloc[1:]
        gain, loss = d.clip(lower=0), (-d).clip(lower=0)
        # Wilder's smoothing is an EMA with alpha 1/14, seeded with the plain average of the first 14 changes
        seed = lambda x: pd.concat([pd.Series([x.iloc[:14].mean()]), x.iloc[14:]]).ewm(alpha=1 / 14, adjust=False).mean()
        ref = (100 - 100 / (1 + seed(gain) / seed(loss))).tolist()
        got = [x for x in agent._rsi(c.tolist()) if x is not None]
        self.assertEqual(len(got), len(ref))
        for g, e in zip(got, ref):
            self.assertAlmostEqual(g, e, places=9)

    def test_extremes(self):
        self.assertAlmostEqual(agent._rsi(list(range(1, 40)))[-1], 100)
        self.assertAlmostEqual(agent._rsi(list(range(40, 1, -1)))[-1], 0)

    def test_short_series(self):
        self.assertEqual(agent._rsi([1, 2, 3]), [])


class Averages(unittest.TestCase):
    def test_sma(self):
        xs = [1, 2, 3, 4, 5, 6]
        self.assertEqual(agent._sma_at(xs, 3, 5), 5)
        self.assertEqual(agent._sma_at(xs, 3, 2), 2)
        self.assertIsNone(agent._sma_at(xs, 3, 1))

    def test_ema_matches_definition(self):
        xs = [10, 11, 12, 11, 13, 15, 14]
        k, e = 2 / 4, xs[0]
        for x in xs[1:]:
            e = x * k + e * (1 - k)
        self.assertAlmostEqual(agent._ema(xs, 3)[-1], e)

    def test_ema_matches_pandas(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas isn't installed")
        xs = [100 + math.sin(i / 3) * 5 + i * 0.1 for i in range(120)]
        for n in (9, 12, 26):
            ref = pd.Series(xs).ewm(span=n, adjust=False).mean().tolist()
            for g, e in zip(agent._ema(xs, n), ref):
                self.assertAlmostEqual(g, e, places=9)

    def test_macd_sign(self):
        up = [100 * 1.01 ** i for i in range(80)]
        e12, e26 = agent._ema(up, 12), agent._ema(up, 26)
        self.assertGreater(e12[-1] - e26[-1], 0)          # a steady rise puts the fast average above the slow


class Levels(unittest.TestCase):
    def test_finds_repeated_peaks_and_troughs(self):
        # a wave between 90 and 110, so the highs cluster near 110 and the lows near 90
        closes = [100 + 10 * math.sin(i / 6) for i in range(160)]
        b = bars(closes, spread=0.002)
        lv, tol = levels.key_levels(b["h"], b["l"], b["c"], b["d"])
        tops = [x for x in lv if x["p"] > 105]
        bottoms = [x for x in lv if x["p"] < 95]
        self.assertEqual(len(tops), 1)
        self.assertEqual(len(bottoms), 1)
        self.assertAlmostEqual(tops[0]["p"], 110, delta=0.6)
        self.assertAlmostEqual(bottoms[0]["p"], 90, delta=0.6)
        self.assertGreaterEqual(tops[0]["touches"], 3)     # the wave peaks several times
        self.assertLessEqual(tops[0]["lo"], tops[0]["p"])
        self.assertGreaterEqual(tops[0]["hi"], tops[0]["p"])
        self.assertEqual(tops[0]["strength"], 3)
        self.assertFalse(tops[0]["flip"])

    def test_a_broken_ceiling_becomes_a_floor(self):
        # three peaks at 110, a break to 120, then two pullbacks that hold at 110: one level, hit from both sides
        closes = ([100 + 10 * math.sin(i / 4) for i in range(75)] + [110 + i for i in range(10)]
                  + [120 - 10 * abs(math.sin(i / 4)) for i in range(40)] + [121] * 3)
        b = bars(closes, spread=0.002)
        lv, tol = levels.key_levels(b["h"], b["l"], b["c"], b["d"])
        at110 = min(lv, key=lambda x: abs(x["p"] - 110))
        self.assertAlmostEqual(at110["p"], 110, delta=1)
        self.assertTrue(at110["flip"])
        near = levels.nearest(lv, 121, tol)
        self.assertEqual(near["resistance"], [])            # above the old highs: nothing overhead
        self.assertTrue(any(x is at110 for x in near["support"]))

    def test_nearest_skips_one_touch_noise(self):
        lv = [{"p": p, "touches": t} for p, t in ((105, 1), (108, 1), (112, 3), (95, 2), (97, 1), (90, 1))]
        near = levels.nearest(lv, 100, tol=1)
        self.assertEqual([x["p"] for x in near["resistance"]], [105, 112])   # the nearest stays even with one touch
        self.assertEqual([x["p"] for x in near["support"]], [97, 95])
        self.assertEqual(levels.nearest(lv, 100.4, tol=1)["here"], [])     # nothing with two touches at the price


class TechnicalsSection(unittest.TestCase):
    def setUp(self):
        agent.srv = FakeServer()

    def text(self, closes):
        return "\n".join(agent.sec_technicals("TEST", bars(closes), {"sector": "Technology"}))

    def test_uptrend(self):
        t = self.text([50 * 1.003 ** i for i in range(300)])
        self.assertIn("Uptrend", t)
        self.assertIn("overbought", t)                     # a straight line up has RSI near 100

    def test_downtrend(self):
        t = self.text([150 * 0.997 ** i for i in range(300)])
        self.assertIn("Downtrend", t)
        self.assertIn("oversold", t)

    def test_golden_cross_date(self):
        closes = [100 * 0.998 ** i for i in range(250)] + [60.6 * 1.01 ** i for i in range(80)]
        b = bars(closes)
        t = "\n".join(agent.sec_technicals("TEST", b, {}))
        self.assertIn("golden cross", t)
        # check the reported date against a direct computation
        n = len(closes)
        diff = [agent._sma_at(closes, 50, i) - agent._sma_at(closes, 200, i) for i in range(199, n)]
        j = max(k for k in range(1, len(diff)) if diff[k] > 0 >= diff[k - 1])
        self.assertIn(b["d"][j + 199], t)

    def test_too_little_history(self):
        self.assertEqual(agent.sec_technicals("TEST", bars([10] * 30), {}), [])


class FundContributions(unittest.TestCase):
    def test_adds_up_to_the_fund_return(self):
        start = [0.5, 0.3, 0.2]
        rets = [0.10, -0.05, 0.02]
        end_value = [w * (1 + r) for w, r in zip(start, rets)]
        today = [v / sum(end_value) for v in end_value]          # what the issuer publishes after the move
        out = agent.contributions(today, rets)
        for (w0, _), s in zip(out, start):
            self.assertAlmostEqual(w0, s)                         # start weights recovered exactly
        basket = sum(end_value) / sum(start) - 1
        self.assertAlmostEqual(sum(c for _, c in out), basket)

    def test_missing_return_contributes_nothing(self):
        out = agent.contributions([0.6, 0.4], [0.1, None])
        self.assertEqual(out[1][1], 0.0)
        self.assertAlmostEqual(sum(w for w, _ in out), 1.0)


class InsiderSection(unittest.TestCase):
    def test_summary_and_cluster(self):
        today = dt.date.today()
        day = lambda n: (today - dt.timedelta(days=n)).isoformat()
        tx = [
            {"date": day(10), "insider": "DOE JANE", "role": "Chief Executive Officer", "what": "buy", "kind": "buy", "shares": 1000, "value": 100000, "price": 100},
            {"date": day(20), "insider": "ROE RICH", "role": "Director", "what": "buy", "kind": "buy", "shares": 500, "value": 50000, "price": 100},
            {"date": day(30), "insider": "ROE RICH", "role": "Director", "what": "sell", "kind": "sell", "shares": 2000, "value": 220000, "price": 110},
            {"date": day(40), "insider": "DOE JANE", "role": "Chief Executive Officer", "what": "award", "kind": "award", "shares": 9000, "value": 0, "price": 0},
        ]
        o = {"insiders": tx, "major": {"insidersPercentHeld": 0.05},
             "roster": [{"name": "ROE RICH", "direct": 8000, "indirect": None}, {"name": "DOE JANE", "direct": 50000, "indirect": 0}]}
        t = "\n".join(agent.sec_insiders(o, 120.0))
        self.assertIn("2 open-market buys by 2 people ($150,000)", t)
        self.assertIn("1 sale by 1 person ($220,000)", t)
        self.assertIn("1 stock award", t)
        self.assertIn("2 insiders from", t)                           # cluster buying flagged
        self.assertIn("| Roe Rich | Director | $50,000 | $220,000 | 2 |", t)
        self.assertIn("| 20% |", t)                                   # sold 2,000 of 10,000 shares
        self.assertIn("+20.0%", t)                                    # bought at $100, now $120


class Money(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(agent._money(1_860_000_000), "$1.86B")
        self.assertEqual(agent._money(960_000_000), "$960.0M")
        self.assertEqual(agent._money(133_750), "$133,750")
        self.assertEqual(agent._money(0), "$0")
        self.assertEqual(agent._money(12.5), "$12.50")


if __name__ == "__main__":
    unittest.main()
