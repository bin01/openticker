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


class IntradayVolume(unittest.TestCase):
    def test_blanks_bogus_bars_and_keeps_real_ones(self):
        import pandas as pd
        idx = pd.date_range("2026-11-10 09:30", periods=24, freq="5min", tz="America/New_York")
        vol = [300_000] * 24
        vol[0] = 2_000_000          # a busy opening bar: real, about 7 times the median
        vol[5] = vol[7] = 20_000_000   # Yahoo's bogus bars, each most of a day's volume
        clean = X.clean_intraday_volume(pd.DataFrame({"Close": [1.0] * 24, "Volume": vol}, index=idx))
        self.assertEqual(clean["Volume"].iloc[0], 2_000_000)
        self.assertEqual(clean["Volume"].iloc[5], 0)
        self.assertEqual(clean["Volume"].iloc[7], 0)
        self.assertEqual(int(clean["Volume"].sum()), 2_000_000 + 21 * 300_000)

    def test_no_volume_column(self):
        import pandas as pd
        df = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.date_range("2026-11-10 09:30", periods=2, freq="5min"))
        self.assertIs(X.clean_intraday_volume(df), df)
