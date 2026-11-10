"""Checks Tick's workbench: the proxy reaches public sites but never this Mac or the local network, files are only
served from a conversation's out/ folder, Claude Code's sandbox settings keep it in its folder, and the `ot` module
hands code the prices."""
import http.server
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
sys.path.insert(0, str(ROOT / "app"))
import workbench  # noqa: E402


class Local(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "5")
        self.end_headers()
        self.wfile.write(b"hello")

    def log_message(self, *a):
        pass


def via_proxy(raw):
    s = socket.create_connection(("127.0.0.1", workbench.start_proxy()), timeout=5)
    s.sendall(raw)
    out = b""
    try:
        while True:
            c = s.recv(4096)
            if not c:
                break
            out += c
            if b"hello" in out or out.startswith(b"HTTP/1.1 403") or out.startswith(b"HTTP/1.1 200 Connection"):
                break
    finally:
        s.close()
    return out


class Proxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Local)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_public_only(self):
        for host in ("127.0.0.1", "localhost", "10.1.2.3", "192.168.1.5", "172.16.0.1", "169.254.169.254", "::1", "0.0.0.0"):
            self.assertIsNone(workbench.public(host, 80), host)
        self.assertIsNotNone(workbench.public("8.8.8.8", 443))

    def test_refuses_this_mac(self):
        out = via_proxy(f"GET http://127.0.0.1:{self.port}/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
        self.assertTrue(out.startswith(b"HTTP/1.1 403"), out[:40])
        out = via_proxy(f"CONNECT localhost:{self.port} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        self.assertTrue(out.startswith(b"HTTP/1.1 403"), out[:40])

    def test_own_data_only(self):
        # OpenTicker's read-only data passes through to this Mac; nothing else does
        with mock.patch.dict(workbench.state, {"serve": (self.port, ("stock", "news"))}):
            ok = via_proxy(f"GET http://127.0.0.1:{self.port}/api/agent/stock?q=NVDA HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
            self.assertIn(b"hello", ok)
            for bad in (f"GET http://127.0.0.1:{self.port}/api/agent/edit?q=x HTTP/1.1\r\n\r\n",
                        f"GET http://127.0.0.1:{self.port}/api/me HTTP/1.1\r\n\r\n",
                        f"POST http://127.0.0.1:{self.port}/api/agent/stock HTTP/1.1\r\nContent-Length: 0\r\n\r\n",
                        f"GET http://127.0.0.1:{self.port}/api/agent/stock HTTP/1.1\r\nContent-Length: 5\r\n\r\n",
                        f"GET http://127.0.0.1:{self.port}/api/agent/stock HTTP/1.1\r\n\r\nGET /api/me HTTP/1.1\r\n\r\n",
                        f"GET http://127.0.0.1:{self.port + 1}/api/agent/stock HTTP/1.1\r\n\r\n",
                        f"CONNECT 127.0.0.1:{self.port} HTTP/1.1\r\n\r\n"):
                self.assertTrue(via_proxy(bad.encode()).startswith(b"HTTP/1.1 403"), bad)

    def test_forwards_when_allowed(self):
        # pretend the local test server is a public one, to see the forwarding itself work
        with mock.patch.object(workbench, "public", lambda h, p: [("127.0.0.1", p)]):
            out = via_proxy(f"GET http://example.test:{self.port}/x HTTP/1.1\r\nHost: example.test\r\nProxy-Connection: keep-alive\r\n\r\n".encode())
            self.assertIn(b"hello", out)
            s = socket.create_connection(("127.0.0.1", workbench.start_proxy()), timeout=5)
            s.sendall(f"CONNECT example.test:{self.port} HTTP/1.1\r\n\r\n".encode())
            self.assertTrue(s.recv(100).startswith(b"HTTP/1.1 200"))
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            got = b""
            while b"hello" not in got:
                c = s.recv(4096)
                if not c:
                    break
                got += c
            s.close()
            self.assertIn(b"hello", got)


class Files(unittest.TestCase):
    def test_only_out_folder(self):
        ws = workbench.space("chat-test-1")
        (ws / "out" / "chart.png").write_bytes(b"png")
        (ws / "secret.txt").write_text("no")
        self.assertEqual(workbench.file_path("chat-test-1", "chart.png"), (ws / "out" / "chart.png").resolve())
        for bad in ("../secret.txt", "out/chart.png", "/etc/passwd", "..", ".hidden", "a/b.png", ""):
            self.assertIsNone(workbench.file_path("chat-test-1", bad), bad)
        self.assertIsNone(workbench.file_path("../spaces", "chart.png"))
        self.assertEqual([f["name"] for f in workbench.outputs(ws, 0)], ["chart.png"])


class Settings(unittest.TestCase):
    def test_claude_stays_in_its_folder(self):
        ws = workbench.space("chat-test-2")
        workbench.start_proxy()
        st = workbench.claude_settings(ws)["sandbox"]
        self.assertTrue(st["enabled"] and st["failIfUnavailable"] and not st["allowUnsandboxedCommands"])
        self.assertTrue(workbench.claude_settings(ws)["disableAllHooks"])
        self.assertEqual(st["filesystem"]["denyRead"], ["~/"])
        self.assertIn("/" + str(ws.resolve()).lstrip("/"), st["filesystem"]["allowWrite"])
        self.assertEqual(st["network"]["httpProxyPort"], workbench.state["proxy"])
        self.assertFalse(st["network"]["allowLocalBinding"])
        tools, allowed = workbench.claude_tools(ws, ("stock", "history"))
        self.assertIn("Bash(openticker stock:*)", allowed)
        self.assertFalse(any(a.startswith("Bash(openticker:") or a == "Bash" for a in allowed))   # never every openticker command

    def test_toolbox_is_read_only(self):
        # one Python toolbox serves every conversation, so code in one conversation's sandbox may run it but not change it
        ws = workbench.space("chat-test-3")
        s = workbench.claude_settings(ws)
        fs = s["sandbox"]["filesystem"]
        a = lambda p: "/" + str(Path(p).resolve()).lstrip("/")
        self.assertEqual(fs["allowWrite"], [a(ws)])                        # its own folder, and nothing else
        for shared in (workbench.TOOLBOX, workbench.CACHE, workbench.SDK, workbench.paths.ROOT):
            self.assertIn(a(shared), fs["denyWrite"])
            self.assertFalse(any(w == a(shared) or w.startswith(a(shared) + "/") for w in fs["allowWrite"]), shared)
            self.assertIn(f"Edit(/{a(shared)}/**)", s["permissions"]["deny"])
            self.assertIn(f"Write(/{a(shared)}/**)", s["permissions"]["deny"])
        self.assertIn(a(workbench.TOOLBOX), fs["allowRead"])                # but it may read and run it
        self.assertFalse(a(ws).startswith(a(workbench.TOOLBOX) + "/"))
        tools, allowed = workbench.claude_tools(ws, ("stock",))
        self.assertFalse(any(str(workbench.TOOLBOX.resolve()) in x for x in allowed if x.startswith(("Edit", "Write"))))

    def test_installs_and_caches_stay_in_the_conversation(self):
        ws = workbench.space("chat-test-4")
        e = workbench.env(ws, {"PATH": "/usr/bin"})
        own = ws / ".openticker"
        self.assertEqual(e["PIP_TARGET"], str(own / "packages"))
        self.assertEqual(e["PYTHONPATH"].split(os.pathsep), [str(workbench.SDK), str(own / "packages")])
        for k in ("PIP_CACHE_DIR", "XDG_CACHE_HOME", "MPLCONFIGDIR"):
            self.assertTrue(e[k].startswith(str(own)), k)
        self.assertEqual(e["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue((own / "packages").is_dir())
        self.assertFalse(hasattr(workbench, "codex_args"))                  # Codex gets no extra writable folder either

    def test_older_toolbox_is_made_again(self):
        # a toolbox from before it was read-only (no pip, no compiled bytecode) doesn't count as ready, so build() remakes it
        with tempfile.TemporaryDirectory() as d, mock.patch.object(workbench, "TOOLBOX", Path(d)):
            (Path(d) / "bin").mkdir()
            (Path(d) / "bin" / "python").write_text("")
            (Path(d) / ".ready").write_text(json.dumps({"packages": workbench.PACKAGES, "at": 1}))
            self.assertIsNone(workbench.python())
            (Path(d) / ".ready").write_text(json.dumps({"packages": workbench.PACKAGES, "at": 1, "v": workbench.TOOLBOX_VERSION}))
            self.assertEqual(workbench.python(), Path(d) / "bin" / "python")

    def test_sandbox_failure_is_recognized(self):
        self.assertTrue(workbench.sandbox_failed("Error: sandbox is not available on this platform"))
        self.assertFalse(workbench.sandbox_failed("rate limit reached"))


class OT(unittest.TestCase):
    def test_prices(self):
        try:
            importlib.import_module("pandas")
        except ImportError:
            self.skipTest("needs pandas")
        d = tempfile.mkdtemp()
        p = Path(d, "history.json")
        p.write_text(json.dumps({"dates": ["2026-01-02", "2026-01-05", "2026-01-06"], "px": {"AAA": [10, None, 12], "BRK-B": [1, 2, 3]}}))
        sys.path.insert(0, str(ROOT / "app" / "sdk"))
        import ot
        with mock.patch.dict(os.environ, {"OT_PRICES": str(p), "OT_WORKSPACE": d}):
            px = ot.prices(["aaa", "BRK.B"])
            self.assertEqual(list(px.columns), ["AAA", "BRK-B"])
            self.assertTrue(px["AAA"].isna().iloc[1])
            self.assertAlmostEqual(ot.returns("BRK-B").iloc[-1, 0], 0.5)
            asked = []   # a ticker OpenTicker doesn't keep goes to Yahoo; here Yahoo is a stub that has nothing
            yf = mock.Mock(download=lambda t, **k: asked.append(t) or importlib.import_module("pandas").DataFrame())
            with mock.patch.dict(sys.modules, {"yfinance": yf}), self.assertRaises(KeyError):
                ot.prices("ZZZ")
            self.assertEqual(asked, [["ZZZ"]])
            self.assertEqual(len(ot.positions()), 0)
            Path(d, ".openticker").mkdir()
            Path(d, ".openticker", "you.json").write_text(json.dumps({"positions": [{"t": "NVDA", "weight": 0.6}, {"t": "AAPL", "weight": 0.4}]}))
            pos = ot.positions()
            self.assertEqual(list(pos.columns), ["t", "weight"])                # weights, never shares or cost
            self.assertAlmostEqual(pos["weight"].sum(), 1.0)


if __name__ == "__main__":
    unittest.main()
