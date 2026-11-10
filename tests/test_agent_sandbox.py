"""Checks how Tick's agents are confined: OpenCode runs as an agent that may only run the read-only data commands and
read the web, Codex's sandbox has no network (with it, it could read the Keychain and reach OpenTicker as this Mac), and
the prompt doesn't promise either of them what they can't do."""
import json
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
import workbench  # noqa: E402


class OpenCode(unittest.TestCase):
    def test_permissions_deny_all_but_data_and_web(self):
        p = agent.opencode_permissions()
        self.assertEqual(p["*"], "deny")
        self.assertEqual((p["webfetch"], p["websearch"]), ("allow", "allow"))
        b = p["bash"]
        self.assertEqual(list(b)[0], "*")
        self.assertEqual(b["*"], "deny")
        self.assertEqual(b["openticker stock *"], "allow")
        self.assertEqual(b["openticker portfolio"], "allow")
        self.assertNotIn("openticker edit *", b)
        self.assertNotIn("openticker update", b)
        # later rules win: chaining, pipes and substitutions are denied after the allowed commands
        keys = list(b)
        for t in agent.SHELL_TRICKS:
            self.assertEqual(b[t], "deny")
            self.assertGreater(keys.index(t), keys.index("openticker stock *"))
        for k in ("read", "edit", "write", "external_directory"):
            self.assertNotIn(k, p)   # covered by "*": deny

    def test_config_file_and_flag(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(agent, "WORK_DIR", Path(d)):
            (Path(d) / "opencode.json").write_text('{"agent": {"openticker-tick": {"permission": {"*": "allow"}}}}')
            agent.opencode_config()
            cfg = json.loads((Path(d) / "opencode.json").read_text())
        self.assertEqual(cfg["agent"][agent.OPENCODE_AGENT]["permission"], agent.opencode_permissions())

        seen = {}
        r = agent.Run("opencode", "q", lambda *a: None)
        r._spawn = lambda args: seen.setdefault("args", args) and (_ for _ in ()).throw(FileNotFoundError())
        with tempfile.TemporaryDirectory() as d, mock.patch.object(agent, "WORK_DIR", Path(d)), \
                mock.patch.object(agent, "_opencode_standalone", return_value=True):
            r.run()
        self.assertIn("--standalone", seen["args"])
        self.assertIn("--agent", seen["args"])
        self.assertEqual(seen["args"][seen["args"].index("--agent") + 1], agent.OPENCODE_AGENT)


class Codex(unittest.TestCase):
    def test_network_off(self):
        seen = {}
        r = agent.Run("codex", "q", lambda *a: None)
        r._spawn = lambda args: seen.setdefault("args", args) and (_ for _ in ()).throw(FileNotFoundError())
        r.run()
        a = " ".join(map(str, seen["args"]))
        self.assertIn("sandbox_workspace_write.network_access=false", a)
        self.assertNotIn("network_access=true", a)

    def test_prompt_matches(self):
        self.assertNotIn("codex", agent.LIVE_DATA)
        self.assertIn("claude", agent.LIVE_DATA)
        off = workbench.note(offline=True)
        self.assertIn("no network", off)
        self.assertNotIn("any public website", off)
        self.assertNotIn("ot.get(url)", off)
        self.assertIn("any public website", workbench.note())


if __name__ == "__main__":
    unittest.main()
