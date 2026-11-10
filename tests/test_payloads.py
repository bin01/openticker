"""Checks the research payloads the page reads: analysts' price targets (a missing target is None, never 0) and the
economic calendar's revised figures (sent only when the previous figure really was revised). Needs no network."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import yahoo_extra as X  # noqa: E402


class PriceTargets(unittest.TestCase):
    def test_target(self):
        self.assertEqual(X.target(210.0), 210.0)
        self.assertEqual(X.target(187.5), 187.5)
        for v in (0, 0.0, None, float("nan"), "", -5.0):   # Yahoo sends 0 for "no prior target"
            self.assertIsNone(X.target(v), v)


class RevisedFigures(unittest.TestCase):
    def test_revised_from(self):
        self.assertEqual(X.revised_from(254.0, 223.0), 223.0)     # payrolls, in thousands, like "last"
        self.assertEqual(X.revised_from(-0.1, 0.2), 0.2)
        self.assertIsNone(X.revised_from(2.9, 2.9))               # not revised: nothing to say
        self.assertIsNone(X.revised_from(2.9, float("nan")))      # yfinance turns a missing figure into NaN
        self.assertIsNone(X.revised_from(None, 2.9))              # no previous figure to have revised
        self.assertIsNone(X.revised_from(2.9, None))
        v = X.revised_from(math.nan, math.nan)
        self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
