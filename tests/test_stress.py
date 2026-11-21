"""Checks the Market page's "Under the hood" gauges (app/stress.py): each reading follows its thresholds, a source
that's down leaves only its own gauge empty, and the headline matches the gauges. Standard library only.

    openticker test        (or: python -m unittest discover tests)
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import stress  # noqa: E402


def days(n):
    return [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def flat(n, v):
    return [float(v)] * n


def prices(n=260, vix=15.0, rsp_drop=0.0, spy_drop=0.0, hb_drop=0.0):
    """Steady prices with the last month moved by the given fractions."""
    def path(drop, start=100.0):
        a = flat(n - 21, start)
        return a + [start * (1 - drop * (i + 1) / 21) for i in range(21)]
    return {"dates": days(n), "px": {"^VIX": flat(n - 1, 15) + [vix], "RSP": path(rsp_drop), "SPY": path(spy_drop),
                                      "SPHB": path(hb_drop), "SPLV": flat(n, 100)}}


def credit(last, month_ago=None, n=300):
    month_ago = last if month_ago is None else month_ago
    vals = flat(n - 22, month_ago) + [month_ago] + [month_ago + (last - month_ago) * (i + 1) / 21 for i in range(21)]
    return list(zip(days(n), vals))


def futures(shift=0.0, n=150):
    """Weekly rows: net short 20% of 1,000,000 contracts, wobbling 1 point a week, then `shift` over the last 4 weeks."""
    rows = []
    for i in range(n):
        net = -0.20 + 0.03 * math.sin(i * 1.7)
        if i >= n - 4:
            net += shift * (i - (n - 5)) / 4
        rows.append((days(n)[i], 400000 + net * 1e6 / 2, 400000 - net * 1e6 / 2, 1e6))
    return {"S&P 500": rows, "Nasdaq-100": futures_quiet(n)}


def futures_quiet(n):
    return [(days(n)[i], 100000.0, 100000.0, 400000.0) for i in range(n)]


def gauge(p, key):
    return next(g for g in p["gauges"] if g["key"] == key)


class StressGauges(unittest.TestCase):
    def test_calm_market_reads_calm(self):
        p = stress.payload(credit(3.0), prices(), futures())
        self.assertEqual([g["state"] for g in p["gauges"]], ["calm"] * 5)
        self.assertEqual(p["head"], "Calm under the hood")

    def test_credit_thresholds(self):
        self.assertEqual(stress.credit(credit(3.0, 2.9))["state"], "calm")
        self.assertEqual(stress.credit(credit(3.5, 3.1))["state"], "watch")       # up 0.4 in a month
        self.assertEqual(stress.credit(credit(4.6))["state"], "watch")            # high, though steady
        self.assertEqual(stress.credit(credit(4.0, 3.2))["state"], "stressed")    # up 0.8 in a month
        self.assertIn("up 0.80 pts in a month", stress.credit(credit(4.0, 3.2))["line"])

    def test_fear_thresholds(self):
        d = days(260)
        self.assertEqual(stress.fear(d, flat(260, 19.9))["state"], "calm")
        self.assertEqual(stress.fear(d, flat(260, 25))["state"], "watch")
        self.assertEqual(stress.fear(d, flat(259, 15) + [35.0])["state"], "stressed")
        self.assertIn("The highest in the past year", stress.fear(d, flat(259, 15) + [35.0])["note"])

    def test_breadth_narrow_vs_broad(self):
        narrow = stress.payload(credit(3.0), prices(rsp_drop=0.05, spy_drop=0.12), futures())
        b = gauge(narrow, "breadth")
        self.assertEqual(b["state"], "watch")
        self.assertTrue(b["data"]["narrow"])
        self.assertIn("biggest companies", narrow["sub"])
        broad = stress.payload(credit(3.0), prices(rsp_drop=0.12, spy_drop=0.06), futures())
        self.assertEqual(gauge(broad, "breadth")["state"], "stressed")
        self.assertIn("broad", broad["sub"])

    def test_appetite(self):
        self.assertEqual(gauge(stress.payload(None, prices(hb_drop=0.06), None), "appetite")["state"], "watch")
        self.assertEqual(gauge(stress.payload(None, prices(hb_drop=0.15), None), "appetite")["state"], "stressed")

    def test_funds_reads_the_speed_not_the_level(self):
        # always net short 20%: the level alone is no signal
        self.assertEqual(stress.funds(futures())["state"], "calm")
        fast = stress.funds(futures(shift=0.10))
        self.assertEqual(fast["state"], "stressed")
        self.assertRegex(fast["line"], r"S&P 500: net short \d+% of contracts, from net short \d+% a month earlier\.")
        self.assertIn("Nasdaq-100: about even, about where it was a month earlier.", fast["line"])

    def test_a_missing_source_leaves_only_its_gauge_empty(self):
        p = stress.payload(None, prices(vix=32), futures(), {"credit": "FRED didn't answer just now."})
        c = gauge(p, "credit")
        self.assertIsNone(c["state"])
        self.assertEqual(c["error"], "FRED didn't answer just now.")
        self.assertEqual(gauge(p, "fear")["state"], "stressed")
        self.assertEqual(p["head"], "Stocks are shaken")
        self.assertIn("not available", stress.text(p))

    def test_headline_follows_credit(self):
        shaken = stress.payload(credit(3.0), prices(vix=32), futures())
        self.assertEqual(shaken["head"], "Stocks are shaken, but bonds are calm")
        spreading = stress.payload(credit(6.0), prices(vix=32), futures())
        self.assertEqual(spreading["head"], "The stress has reached the bond market")

    def test_nothing_at_all(self):
        p = stress.payload()
        self.assertIsNone(p["head"])
        self.assertTrue(all(g["state"] is None for g in p["gauges"]))


if __name__ == "__main__":
    unittest.main()
