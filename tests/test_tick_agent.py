"""Checks how Tick explains an agent's failure, and that a playbook goes only to agents that can run it (metadata.needs)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
sys.path.insert(0, str(ROOT / "app"))
import agent  # noqa: E402
import runs  # noqa: E402
import workbench  # noqa: E402


class Explain(unittest.TestCase):
    def explain(self, tail):
        return agent.Run("codex", "q", lambda *a: None)._explain(tail)

    def test_signed_out(self):
        for tail in ("Error: not logged in", "Please run /login", "401 Unauthorized", "OAuth token has expired",
                     "auth error: token revoked", "Authentication required", "Invalid API key"):
            self.assertIn("isn't signed in", self.explain(tail), tail)

    def test_other_words_are_not_sign_in(self):
        for tail in ("could not parse author field", "certificate authority unknown", "blogin.py crashed", "dialog in use"):
            self.assertIn("stopped unexpectedly", self.explain(tail), tail)

    def test_usage_limit(self):
        self.assertIn("usage limit", self.explain("You've hit your usage limit"))


class Needs(unittest.TestCase):
    def test_every_need_is_known(self):
        for s in agent.skills():
            self.assertLessEqual(set(s["needs"]), set(agent.NEEDS), s["name"])
        self.assertEqual(agent.skill("company-deep-dive")["needs"], ["workbench", "web"])

    def test_who_can_run_the_deep_dive(self):
        dd = agent.skill("company-deep-dive")
        with mock.patch.object(workbench, "claude_ready", return_value=True):
            self.assertEqual([p for p in ("claude", "codex", "opencode", "ollama") if agent.usable(dd, p)], ["claude"])
        with mock.patch.object(workbench, "claude_ready", return_value=False):   # sandbox off for the hour
            self.assertFalse(agent.usable(dd, "claude"))
        self.assertFalse(agent.usable(dd, "claude", bench=False))
        self.assertTrue(agent.usable(agent.skill("stock-snapshot"), "ollama"))

    def test_typed_question_matches_only_what_the_agent_can_run(self):
        q = "what's priced in at this price?"
        with mock.patch.object(workbench, "claude_ready", return_value=True):
            self.assertEqual(agent.match_skill(q, "stock", "claude")["name"], "company-deep-dive")
        self.assertIsNone(agent.match_skill(q, "stock", "ollama"))
        self.assertIsNone(agent.match_skill(q, "stock", "codex"))

    def test_answer_drops_a_playbook_its_agent_cant_run(self):
        spec = {"skill": "company-deep-dive"}
        self.assertIsNone(runs._skill(spec, "ollama", False))
        self.assertIsNone(runs._skill(spec, "claude", False))
        self.assertEqual(runs._skill(spec, "claude", True)["name"], "company-deep-dive")
        self.assertEqual(runs._skill({"skill": "stock-snapshot"}, "ollama", False)["name"], "stock-snapshot")


if __name__ == "__main__":
    unittest.main()
