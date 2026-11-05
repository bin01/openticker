"""Checks the watchlist and positions editors' saves: everything applies together, and only to the person's own rows."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import personal  # noqa: E402


class Editors(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        for t in ("AAPL", "NVDA", "TSM"):
            personal.set_watch("me", t, True)
        self.a = personal.add_position("me", "AAPL", 10, 150)
        self.b = personal.add_position("me", "NVDA", 30, 48)
        self.other = personal.add_position("you", "MSFT", 5, 300)

    def tearDown(self):
        personal._conn.close()
        personal._conn = self.old

    def test_watch_adds_and_removes_together(self):
        personal.save_watch("me", add=["AMD", "AAPL"], remove=["NVDA"])
        self.assertEqual(sorted(personal.watchlist("me")), ["AAPL", "AMD", "TSM"])

    def test_positions_update_add_delete(self):
        personal.save_positions("me", update=[(self.a, 12, 151.5, "2024-02-01")], add=[("AMZN", 4, 135, "")], delete=[self.b])
        got = {p["t"]: (p["shares"], p["cost"], p["opened"]) for p in personal.positions("me")}
        self.assertEqual(got, {"AAPL": (12, 151.5, "2024-02-01"), "AMZN": (4, 135, "")})

    def test_cannot_touch_someone_elses_rows(self):
        personal.save_positions("me", update=[(self.other, 1, 1, "")], delete=[self.other])
        self.assertEqual([(p["shares"], p["cost"]) for p in personal.positions("you")], [(5, 300)])


if __name__ == "__main__":
    unittest.main()
