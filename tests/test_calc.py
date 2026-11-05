"""Checks `openticker calc`, where Tick's agents do their math: the prices arrive as pandas, errors come back short,
runaway code is stopped, and on a Mac the sandbox really keeps the code away from the network and your files."""
import importlib.machinery
import importlib.util
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ld = importlib.machinery.SourceFileLoader("openticker_cli", str(ROOT / "bin" / "openticker"))
cli = importlib.util.module_from_spec(importlib.util.spec_from_loader("openticker_cli", _ld))
_ld.exec_module(cli)

DATA = {"dates": ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
        "px": {"AAA": [100, 110, None, 99], "SPY": [500, 505, 510, 500]}}
MAC = sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec")


def has_pandas():
    try:
        return bool(cli.subprocess.run([cli.py(), "-c", "import pandas"], capture_output=True).returncode == 0)
    except Exception:
        return False


@unittest.skipUnless(has_pandas(), "needs OpenTicker's Python environment")
class Calc(unittest.TestCase):
    sandbox = False

    def run_(self, code, data=DATA):
        return cli.run_calc(code, data, sandbox=self.sandbox)

    def test_prices_arrive_as_pandas(self):
        rc, out = self.run_("print(round(px['AAA'].iloc[-1] / px['AAA'].iloc[0] - 1, 4), px.shape, int(px['AAA'].isna().sum()))")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip(), "-0.01 (4, 2) 1")
        rc, out = self.run_("print(round(rets['SPY'].iloc[0], 4), len(rets))")
        self.assertEqual(out.strip(), "0.01 3")

    def test_errors_are_short(self):
        rc, out = self.run_("x = 1\nprint(1/0)")
        self.assertEqual(rc, 1)
        self.assertIn('line 2', out)
        self.assertIn("ZeroDivisionError", out)
        self.assertLess(len(out.splitlines()), 3)

    def test_silence_and_long_output(self):
        self.assertIn("Nothing printed", self.run_("x = 1")[1])
        rc, out = self.run_("print('x' * 50000)")
        self.assertLess(len(out), cli.CALC_LIMIT + 200)
        self.assertIn("cut off", out)

    def test_runaway_code_is_stopped(self):
        old, cli.CALC_SECONDS = cli.CALC_SECONDS, 2
        try:
            rc, out = self.run_("while True: pass", {"dates": [], "px": {}})
        finally:
            cli.CALC_SECONDS = old
        self.assertEqual(rc, 1)
        self.assertIn("stopped", out)


@unittest.skipUnless(MAC and has_pandas(), "the sandbox is macOS's")
class Sandbox(Calc):
    sandbox = True

    def test_no_network(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            rc, out = self.run_(f"import socket\ntry:\n    socket.create_connection(('127.0.0.1', {srv.getsockname()[1]}), 2); print('connected')\n"
                                "except OSError as e: print('blocked')")
        finally:
            srv.close()
        self.assertEqual(out.strip(), "blocked", out)

    def test_cant_read_or_write_your_files(self):
        with tempfile.NamedTemporaryFile("w", dir=Path.home(), prefix=".openticker-calc-test-", delete=False) as f:
            f.write("secret")
        try:
            rc, out = self.run_(f"try:\n    print(open({f.name!r}).read())\nexcept OSError: print('blocked')")
            self.assertEqual(out.strip(), "blocked", out)
            rc, out = self.run_(f"try:\n    open({f.name!r}, 'w').write('x'); print('wrote')\nexcept OSError: print('blocked')")
            self.assertEqual(out.strip(), "blocked", out)
            self.assertEqual(Path(f.name).read_text(), "secret")
        finally:
            os.unlink(f.name)

    def test_no_other_programs(self):
        rc, out = self.run_("import subprocess\ntry:\n    subprocess.run(['/bin/echo', 'hi']); print('ran')\nexcept OSError: print('blocked')")
        self.assertEqual(out.strip(), "blocked", out)


if __name__ == "__main__":
    unittest.main()
