"""Checks how Tick explains an agent's failure, that a playbook goes only to agents that can run it (metadata.needs),
and that the person's holdings reach Tick's agents as weights unless a data command asks for the exact figures."""
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
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


def fake_server():
    """Just enough of server.py for the portfolio text: two lots of NVDA and one of AAPL, AMD on the watchlist."""
    snap = {"watch": ["AMD"], "positions": [
        {"t": "NVDA", "shares": 30, "cost": 101.25, "opened": "2023-02-03", "note": "rollover IRA"},
        {"t": "NVDA", "shares": 10, "cost": 140.0, "opened": "2024-05-06", "note": ""},
        {"t": "AAPL", "shares": 7, "cost": 150.5, "opened": "2022-01-04", "note": ""}]}
    dates = ["2026-11-05", "2026-11-06", "2026-11-09"]
    px = {"NVDA": [180.0, 190.0, 200.0], "AAPL": [250.0, 245.0, 240.0], "AMD": [150.0, 152.0, 155.0]}
    return SimpleNamespace(
        personal=SimpleNamespace(snapshot=lambda uid: snap), NY=dt.timezone.utc, EARN={}, FUNDS=[],
        S=SimpleNamespace(lock=threading.Lock(), dates=dates, px=px, ext_view=lambda: {}, sectors={}),
        X=SimpleNamespace(ny_today=lambda: dt.date(2026, 11, 10)), brief=lambda uid: {"items": [], "pending": False})


class Holdings(unittest.TestCase):
    """NVDA is 40 shares at $200 = $8,000 and AAPL 7 at $240 = $1,680, so 82.6% and 17.4% of $9,680."""
    EXACT = ("40 ", "30 ", "$110.94", "110.9", "$150.50", "$8,000", "$9,680", "9,680", "$1,680", "2023-02-03", "rollover", "cost")

    def setUp(self):
        p = mock.patch.object(agent, "srv", fake_server())
        p.start()
        self.addCleanup(p.stop)

    def test_prompt_context_has_weights_not_amounts(self):
        for ctx in (agent.context_for("portfolio", None, 1), agent.portfolio_context(1, exact=False)):
            self.assertIn("| NVDA | 82.6% |", ctx)
            self.assertIn("| AAPL | 17.4% |", ctx)
            for bad in self.EXACT:
                self.assertNotIn(bad, ctx.replace("shares, cost and dollar amounts aren't shown", ""), bad)

    def test_stock_context_line_has_weight_only(self):
        line = " ".join(agent._my_position("NVDA", 1, exact=False))   # as stock_context asks for it
        self.assertIn("82.6% of your portfolio", line)
        for bad in ("40", "110", "8,000", "$"):
            self.assertNotIn(bad, line)
        self.assertIn("watchlist", " ".join(agent._my_position("AMD", 1, exact=False)))

    def test_portfolio_command_still_has_exact_figures(self):
        out = agent.text_for("portfolio", {}, 1)        # `openticker portfolio`, on demand
        self.assertIn("| NVDA | 40 | $110.94 | $200.00 | $8,000 | 82.6% |", out)
        self.assertIn("| AAPL | 7 | $150.50 | $240.00 | $1,680 | 17.4% |", out)
        self.assertIn("Value $9,680", out)
        self.assertIn("portfolio", agent.AGENT_CMDS)       # and Tick's agents may run it
        self.assertIn("openticker portfolio", agent.TOOLS_NOTE)
        self.assertIn("You own 40 shares, average cost $110.94", " ".join(agent._my_position("NVDA", 1, exact=True)))

    def test_workbench_gets_weights_only(self):
        ws = workbench.space("chat-holdings-1", uid=1)
        you = json.loads((ws / ".openticker" / "you.json").read_text())
        self.assertEqual(you["positions"], [{"t": "NVDA", "weight": 0.8264}, {"t": "AAPL", "weight": 0.1736}])
        self.assertEqual(you["watchlist"], ["AMD"])
        self.assertNotRegex(json.dumps(you), r"shares|cost|opened|note|rollover")

    def test_instructions_keep_holdings_off_the_web(self):
        for text in (agent.SYSTEM, (ROOT / "skills" / "openticker" / "SKILL.md").read_text()):
            self.assertRegex(text, r"[Nn]ever put the (person|user)'s holdings, amounts or account details into a web request, search query or URL")
        self.assertIn("Never put holdings or amounts into a URL", workbench.note())
        self.assertNotIn("openticker portfolio", workbench.note(offline=True))   # Codex can't run it, so it isn't told to


if __name__ == "__main__":
    unittest.main()
