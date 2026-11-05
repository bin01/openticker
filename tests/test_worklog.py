"""Checks the work log Tick keeps of an answer (runs.summary): notes, thinking, tool steps with their details, and why
a step failed. The page builds the same log live (askApply in ask.js)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
sys.path.insert(0, str(ROOT / "app"))
import agent  # noqa: E402
import runs  # noqa: E402


class WorkLog(unittest.TestCase):
    def test_summary(self):
        ev = [("status", {"text": "Gathering the data"}), ("status", {"text": "Asking Claude Code"}),
              ("think", {"text": "", "new": True}), ("think", {"text": "Need prices "}), ("think", {"text": "for both."}),
              ("text", {"text": "Let me pull the numbers."}),
              ("status", dict(agent._tool_step("Bash", {"command": "openticker stock NVDA"}), id="a")),
              ("status", dict(agent._tool_step("Bash", {"command": "curl -s https://www.sec.gov/x", "description": "Fetch the filing list"}), id="b")),
              ("fail", {"id": "b", "text": "403"}),
              ("think", {"text": "", "new": True}),
              ("text", {"text": "NVDA fell further."})]
        acc = runs.summary([(0, k, p) for k, p in ev], "Claude Code")
        st = acc["steps"]
        self.assertEqual(st[0], {"n": "Need prices for both.", "th": 1})
        self.assertEqual(st[1], {"n": "Let me pull the numbers."})
        self.assertEqual((st[2]["k"], st[2]["d"]), ("data", "openticker stock NVDA"))
        self.assertEqual((st[3]["t"], st[3]["k"], st[3]["x"]), ("Fetch the filing list", "run", "403"))
        self.assertEqual(len(st), 4)                      # the empty thinking block is dropped
        self.assertEqual(acc["text"], "NVDA fell further.")

    def test_step_details(self):
        w = agent._tool_step("Write", {"file_path": "/x/y/dd.py", "content": "print(1)"})
        self.assertEqual((w["text"], w["kind"], w["detail"]), ("Writing dd.py", "write", "dd.py\n\nprint(1)"))
        self.assertEqual(agent._tool_step("WebFetch", {"url": "https://a.b/c"})["detail"], "https://a.b/c")
        self.assertEqual(agent._result_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]), "a\nb")


if __name__ == "__main__":
    unittest.main()
