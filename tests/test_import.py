"""Checks importing positions from a broker's file: the page's CSV reader on Fidelity- and Schwab-shaped
exports, and that replacing positions really replaces them. Uses an in-memory database."""
import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import personal  # noqa: E402


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's script")
class BrokerFiles(unittest.TestCase):
    def parse(self, *names):
        files = [str(ROOT / "tests" / "fixtures" / n) for n in names]
        out = subprocess.run(["node", str(ROOT / "tests" / "parse_broker.js"), str(ROOT / "app" / "index.html"), *files],
                             capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_fidelity(self):
        p = self.parse("broker-fidelity.csv")[0]
        rows = {r["t"]: r for r in p["rows"]}
        self.assertEqual(sorted(rows), ["AAPL", "BRK.B", "NVDA"])          # no cash, no option, no footer
        self.assertEqual(rows["AAPL"]["shares"], 30)                        # two accounts, one position
        self.assertAlmostEqual(rows["AAPL"]["cost"], (25 * 150 + 5 * 200) / 30, places=3)
        self.assertEqual(rows["NVDA"]["cost"], 60)                          # "$2,400.00" total over 40 shares
        self.assertEqual(len(p["skip"]["other"]), 1)                        # the option

    def test_schwab(self):
        p = self.parse("broker-schwab.csv")[0]
        rows = {r["t"]: r for r in p["rows"]}
        self.assertEqual(sorted(rows), ["AMD", "MSFT", "VOO"])              # header found below the preamble
        self.assertEqual(rows["MSFT"]["cost"], 300)                         # Schwab's Cost Basis is the total
        self.assertIsNone(rows["AMD"]["cost"])                              # "--" means unknown, not zero


class ImportPositions(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        personal.add_position("me", "TSLA", 2, 200)

    def tearDown(self):
        personal._conn.close()
        personal._conn = self.old

    def held(self):
        return sorted(p["t"] for p in personal.snapshot("me")["positions"])

    def test_add_keeps_what_was_there(self):
        personal.import_positions("me", [("AAPL", 30, 158.33), ("NVDA", 40, 60)])
        self.assertEqual(self.held(), ["AAPL", "NVDA", "TSLA"])

    def test_replace_clears_first(self):
        personal.import_positions("me", [("AAPL", 30, 158.33)], replace=True)
        self.assertEqual(self.held(), ["AAPL"])


if __name__ == "__main__":
    unittest.main()
