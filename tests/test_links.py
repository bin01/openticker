"""Checks linked accounts (links.py, mcp_client.py) against a fake brokerage MCP server on this machine: the sign-in
with PKCE and dynamic registration, reading holdings through an accounts tool, never calling a tool that trades,
mirroring a link into the portfolio without touching your own positions, and tokens refreshing on their own.
Also reads a Monarch-shaped reply. Uses an in-memory database and a temporary folder for secrets."""
import base64
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ["OPENTICKER_SECRETS"] = "file"
import links  # noqa: E402
import mcp_client as M  # noqa: E402
import paths  # noqa: E402
import personal  # noqa: E402

POSITIONS = {
    "U111": [{"ticker": "NVDA", "position": 100, "avgCost": 95.5, "assetClass": "STK", "acctId": "U111"},
             {"ticker": "AAPL", "position": 10, "avgCost": 150, "assetClass": "STK", "acctId": "U111"},
             {"ticker": "NVDA 250117C00150000", "position": 2, "avgCost": 1200, "assetClass": "OPT", "acctId": "U111"},
             {"ticker": "USD", "position": 5000, "assetClass": "CASH", "acctId": "U111"}],
    "U222": [{"ticker": "MSFT", "position": 5, "avgCost": 300, "assetClass": "STK", "acctId": "U222"}],
}
TOOLS = [
    {"name": "get_accounts", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_positions", "inputSchema": {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]}},
    {"name": "place_order", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "portfolio_rebalance", "annotations": {"readOnlyHint": False}, "inputSchema": {"type": "object", "properties": {}}},
]


class Fake:
    """The fake provider's state: what it issued and what it was asked."""
    def __init__(self):
        self.codes, self.tokens, self.refresh, self.calls, self.revoked = {}, set(), set(), [], []
        self.registered = None
        self.rotate = False         # retire each refresh token once it's used, as providers that rotate them do


def make_handler(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def out(self, code, obj=None, ctype="application/json", headers=None):
            body = b"" if obj is None else (obj if isinstance(obj, bytes) else json.dumps(obj).encode())
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def base(self):
            return f"http://127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if self.path == "/.well-known/oauth-protected-resource/mcp":
                return self.out(200, {"resource": self.base() + "/mcp", "authorization_servers": [self.base()],
                                      "scopes_supported": ["mcp.read", "mcp.write", "mcp.orders.submit"]})
            if self.path == "/.well-known/oauth-authorization-server":
                b = self.base()
                return self.out(200, {"issuer": b, "authorization_endpoint": b + "/authorize", "token_endpoint": b + "/token",
                                      "registration_endpoint": b + "/register", "revocation_endpoint": b + "/revoke"})
            if self.path.startswith("/authorize?"):   # the person signs in and allows: straight back with a code
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                code = "code-" + str(len(fake.codes))
                fake.codes[code] = {k: q[k][0] for k in q}
                return self.out(302, headers={"Location": q["redirect_uri"][0] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"][0]})})
            self.out(404)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/register":
                fake.registered = json.loads(raw)
                return self.out(201, {"client_id": "client-1", "token_endpoint_auth_method": "none"})
            if self.path == "/token":
                f = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
                if f["grant_type"] == "authorization_code":
                    req = fake.codes.pop(f["code"], None)
                    want = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                    if not req or req["code_challenge"] != want or req["redirect_uri"] != f["redirect_uri"]:
                        return self.out(400, {"error": "invalid_grant"})
                elif f["grant_type"] != "refresh_token" or f["refresh_token"] not in fake.refresh:
                    return self.out(400, {"error": "invalid_grant"})
                elif fake.rotate:
                    fake.refresh.discard(f["refresh_token"])
                tok, ref = f"tok-{len(fake.tokens)}", f"ref-{len(fake.tokens)}"
                fake.tokens.add(tok)
                fake.refresh.add(ref)
                return self.out(200, {"access_token": tok, "refresh_token": ref, "expires_in": 3600, "token_type": "Bearer"})
            if self.path == "/revoke":
                fake.revoked.append(urllib.parse.parse_qs(raw.decode())["token"][0])
                return self.out(200, {})
            if self.path != "/mcp":
                return self.out(404)
            tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            if tok not in fake.tokens:
                return self.out(401, {"error": "unauthorized"}, headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base()}/.well-known/oauth-protected-resource/mcp"'})
            msg = json.loads(raw)
            if "id" not in msg:
                return self.out(202)
            m, p = msg["method"], msg.get("params") or {}
            if m == "initialize":
                res = {"protocolVersion": p["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-broker"}}
                return self.out(200, {"jsonrpc": "2.0", "id": msg["id"], "result": res}, headers={"Mcp-Session-Id": "s1"})
            if m == "tools/list":
                return self.out(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": TOOLS}})
            if m == "tools/call":
                fake.calls.append(p["name"])
                if p["name"] == "get_accounts":
                    data = {"accounts": [{"accountId": "U111", "accountName": "Individual"}, {"accountId": "U222", "accountName": "Roth IRA"}]}
                elif p["name"] == "get_positions":
                    data = POSITIONS[p["arguments"]["account_id"]]
                else:
                    data = {"done": True}
                res = {"content": [{"type": "text", "text": json.dumps(data)}]}
                sse = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': res})}\n\n".encode()
                return self.out(200, sse, "text/event-stream")
            self.out(200, {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no such method"}})

        def do_DELETE(self):
            self.out(200)
    return H


class FakeS:
    def __init__(self):
        self.lock, self.version = threading.Lock(), 0
        self.px = {t: [100.0, 101.0] for t in ("NVDA", "AAPL", "MSFT", "TSLA", "AMD", "VFIAX", "SPY")}

    def track_many(self, syms):
        return {s for s in syms if s in self.px}


class Links(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.fake))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/mcp"
        self.old_conn, self.old_data = personal._conn, paths.DATA
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        self.tmp = tempfile.TemporaryDirectory()
        paths.DATA = Path(self.tmp.name)
        import re
        srv = types.SimpleNamespace(S=FakeS(), PORT=8765, VALID=re.compile(r"[A-Z]{1,5}(-[A-Z]{1,2})?"),
                                    yahoo_symbol=lambda t: t.strip().upper().replace(".", "-").replace(" ", "-"), log=lambda *a: None)
        links.bind(srv)
        links.PENDING.clear()
        links.PREVIEW.clear()
        personal.add_position("me", "TSLA", 3, 200)          # one of your own, which links must never touch

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        personal._conn.close()
        personal._conn, paths.DATA = self.old_conn, self.old_data
        self.tmp.cleanup()

    def sign_in(self, out=None):
        """Connect (or sign in again), follow the provider's sign-in like a browser would, and land on the callback."""
        out = out or links.connect("me", "other", self.url, "Fake Broker")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(out["auth_url"]).query)
        self.assertEqual(q["scope"], ["mcp.read"])                       # read-only, never orders
        self.assertEqual(q["code_challenge_method"], ["S256"])

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        try:
            urllib.request.build_opener(NoRedirect).open(out["auth_url"])
        except urllib.error.HTTPError as e:
            back = e.headers["Location"]
        self.assertTrue(back.startswith("http://127.0.0.1:8765/api/links/callback?"))
        ok, msg = links.callback(urllib.parse.parse_qs(urllib.parse.urlsplit(back).query))
        self.assertTrue(ok, msg)
        self.settle(out["id"])
        return out["id"]

    def settle(self, lid):
        for _ in range(100):   # reads run in the background
            if personal.link("me", lid)["status"] != "fetching":
                break
            threading.Event().wait(0.05)

    def linked(self):
        lid = self.sign_in()
        links.apply("me", lid)
        return lid

    def restart(self):
        links.PENDING.clear()
        links.PREVIEW.clear()
        links._after_restart()

    def test_restart_during_review_reads_again(self):
        lid = self.sign_in()
        self.restart()
        self.assertEqual(personal.link("me", lid)["status"], "fetching")   # not a Review button with nothing behind it
        links._read_again()
        self.settle(lid)
        self.assertEqual(personal.link("me", lid)["status"], "review")
        self.assertIsNotNone(links.preview("me", lid))

    def test_lost_review_can_be_read_again(self):
        lid = self.sign_in()
        links.PREVIEW.clear()
        links.retry("me", lid)
        self.settle(lid)
        self.assertIsNotNone(links.preview("me", lid))

    def test_restart_during_sign_in_asks_again(self):
        out = links.connect("me", "other", self.url, "Fake Broker")
        self.restart()
        self.assertEqual(personal.link("me", out["id"])["status"], "auth")
        links.cancel("me", out["id"])                                    # a link that never synced can still go
        self.assertIsNone(personal.link("me", out["id"]))

    def test_sign_in_again_syncs_straight_away(self):
        lid = self.linked()
        personal.update_link("me", lid, status="auth", error="The sign-in expired. Connect again.")
        self.sign_in(links.reconnect("me", lid))
        link = personal.link("me", lid)
        self.assertEqual((link["status"], link["error"]), ("ok", ""))      # no second review
        self.assertFalse(link["id"] in links.PREVIEW)

    def test_cancel_sign_in_again_keeps_the_link(self):
        lid = self.linked()
        personal.update_link("me", lid, status="auth")
        links.reconnect("me", lid)
        links.cancel("me", lid)
        self.assertEqual(personal.link("me", lid)["status"], "auth")       # back where it was, Sign in again still there
        self.assertFalse(any(v["lid"] == lid for v in links.PENDING.values()))
        self.assertTrue(any(p["source"] == lid for p in personal.positions("me")))

    def test_saying_no_to_sign_in_again_keeps_the_link(self):
        lid = self.linked()
        out = links.reconnect("me", lid)
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(out["auth_url"]).query)["state"][0]
        ok, _ = links.callback({"state": [state], "error": ["access_denied"]})
        self.assertFalse(ok)
        self.assertEqual(personal.link("me", lid)["status"], "auth")

    def test_try_again_after_a_failed_first_read(self):
        lid = self.sign_in()
        personal.update_link("me", lid, status="error", error="The server answered 400.")
        links.retry("me", lid)
        for _ in range(100):
            if personal.link("me", lid)["status"] != "fetching":
                break
            threading.Event().wait(0.05)
        self.assertEqual((personal.link("me", lid)["status"], personal.link("me", lid)["error"]), ("review", ""))
        with self.assertRaises(ValueError):
            links.retry("me", lid)                                     # only a failed link can be tried again

    def test_sign_in_review_and_mirror(self):
        lid = self.sign_in()
        self.assertEqual(self.fake.registered["redirect_uris"], ["http://127.0.0.1:8765/api/links/callback"])
        self.assertEqual(personal.link("me", lid)["status"], "review")
        p = links.preview("me", lid)
        self.assertEqual({r["t"] for r in p["rows"]}, {"NVDA", "AAPL", "MSFT"})
        self.assertEqual(p["accounts"], {"Individual": 2, "Roth IRA": 1})
        self.assertEqual(p["skipped"]["options"], 1)
        self.assertEqual(p["skipped"]["cash"], 1)
        self.assertNotIn("place_order", self.fake.calls)
        self.assertNotIn("portfolio_rebalance", self.fake.calls)
        self.assertEqual(links.apply("me", lid, off=["Roth IRA"]), 2)
        held = {(x["t"], x["source"]) for x in personal.positions("me")}
        self.assertEqual(held, {("TSLA", ""), ("NVDA", lid), ("AAPL", lid)})
        nv = next(x for x in personal.positions("me") if x["t"] == "NVDA")
        self.assertEqual((nv["shares"], nv["cost"], nv["account"]), (100, 95.5, "Individual"))

        # the broker sells AAPL: the next sync mirrors it, keeps Roth IRA left out, and leaves TSLA alone
        POSITIONS["U111"] = [r for r in POSITIONS["U111"] if r["ticker"] != "AAPL"]
        self.assertEqual(links.sync("me", lid), 1)
        self.assertEqual(sorted(x["t"] for x in personal.positions("me")), ["NVDA", "TSLA"])

        # your own edits can't change a linked position
        personal.save_positions("me", update=[(nv["id"], 1, 1, "")], delete=[nv["id"]])
        self.assertEqual(next(x for x in personal.positions("me") if x["t"] == "NVDA")["shares"], 100)

        # an expired token refreshes on its own
        sec = links.get_secret(lid)
        old = sec["token"]["access_token"]
        sec["token"]["expires_at"] = 0
        links.put_secret(lid, sec)
        links.sync("me", lid)
        self.assertNotEqual(links.get_secret(lid)["token"]["access_token"], old)

        # tokens never reach the page
        self.assertNotIn("tok-", json.dumps(links.public(personal.link("me", lid))))

        links.disconnect("me", lid)
        self.assertEqual([x["t"] for x in personal.positions("me")], ["TSLA"])
        self.assertIsNone(links.get_secret(lid))
        self.assertTrue(self.fake.revoked)

    def test_rotated_refresh_token_is_kept(self):
        """A provider that retires each refresh token once used: every sync saves the new one, so the next works too
        (the TokenRefresh model's OneSync config)."""
        lid = self.sign_in()
        links.apply("me", lid)
        self.fake.rotate = True
        for _ in range(3):
            sec = links.get_secret(lid)
            sec["token"]["expires_at"] = 0
            links.put_secret(lid, sec)
            links.sync("me", lid)
            self.assertIn(links.get_secret(lid)["token"]["refresh_token"], self.fake.refresh)
        self.assertEqual(personal.link("me", lid)["status"], "ok")

    def test_two_syncs_at_once_stay_signed_in(self):
        """The daily sync and Sync now at the same moment, with a provider that rotates refresh tokens and answers
        slowly: the second waits for the first and uses the token it saved (the TokenRefresh model's Overlap config)."""
        lid = self.sign_in()
        links.apply("me", lid)
        self.fake.rotate = True
        sec = links.get_secret(lid)
        sec["token"]["expires_at"] = 0
        links.put_secret(lid, sec)
        real, errs = M.refresh, []

        def slow(*a):
            threading.Event().wait(0.3)
            return real(*a)

        def go():
            try:
                links.sync("me", lid)
            except ValueError as e:
                errs.append(str(e))
        M.refresh = slow
        try:
            ts = [threading.Thread(target=go) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            M.refresh = real
        self.assertEqual(errs, [])
        self.assertEqual(personal.link("me", lid)["status"], "ok")
        self.assertIn(links.get_secret(lid)["token"]["refresh_token"], self.fake.refresh)

    def test_callback_needs_our_state(self):
        links.connect("me", "other", self.url)
        ok, _ = links.callback({"state": ["made-up"], "code": ["code-0"]})
        self.assertFalse(ok)

    def test_only_https(self):
        with self.assertRaises(ValueError):
            links.connect("me", "other", "http://example.com/mcp")


class Replies(unittest.TestCase):
    def test_monarch_shape(self):
        reply = {"result": json.dumps({"investments": [
            {"ticker": "AMD", "quantity": 30, "value": 3000, "variation_dollars": 1500, "security_type": "equity",
             "account_holdings": [{"account_name": "Brokerage (...1234)", "quantity": 20}, {"account_name": "IRA (...9)", "quantity": 10}]},
            {"ticker": "USD-USD", "quantity": 500, "value": 500, "variation_dollars": 0, "security_type": "cash", "account_holdings": []},
            {"ticker": "BTC-USD", "quantity": 1, "value": 70000, "variation_dollars": 0, "security_type": "cryptocurrency"},
            {"ticker": "VFIAX", "quantity": 5, "value": 3000, "variation_dollars": -100, "security_type": "mutual_fund", "account_holdings": []},
            {"quantity": 3, "value": 300, "variation_dollars": 0, "security_type": "mutual_fund"},
        ]})}
        data = M.tool_data({"content": [{"type": "text", "text": json.dumps(reply)}]})
        rows, skipped = links.normalize(data)
        amd = [r for r in rows if r["t"] == "AMD"]
        self.assertEqual([(r["account"], r["shares"]) for r in amd], [("Brokerage (...1234)", 20), ("IRA (...9)", 10)])
        self.assertEqual(amd[0]["cost"], 50)                              # (3000 - 1500) / 30
        self.assertEqual(next(r for r in rows if r["t"] == "VFIAX")["account"], "Other accounts")
        self.assertEqual((skipped["cash"], skipped["crypto"]), (1, 1))

    def test_ibkr_shape(self):
        # what IBKR's get_account_positions sent back on 2026-11-06 (numbers changed)
        data = {"positions": [
            {"contract_id": 1, "contract_description": "2DG", "position": 1100.0, "market_price": 1.43, "currency": "EUR", "average_price": 4.03, "asset_class": "STK"},
            {"contract_id": 2, "contract_description": "AAOI", "position": 0.0, "market_price": 30.0, "currency": "USD", "average_price": 0.0, "asset_class": "STK"},
            {"contract_id": 3, "contract_description": "NVDA", "position": 400.0, "market_price": 190.0, "currency": "USD", "average_price": 120.5, "asset_class": "STK"},
            {"contract_id": 4, "contract_description": "NVDA 20DEC26 200 C", "position": 2.0, "currency": "USD", "average_price": 900.0, "asset_class": "OPT"},
        ]}
        rows, skipped = links.normalize(data)
        self.assertEqual(rows, [{"t": "NVDA", "shares": 400.0, "cost": 120.5, "account": ""}])
        self.assertEqual((skipped["foreign"], skipped["options"]), (["2DG"], 1))

    def test_moved_preset_address(self):
        self.assertEqual(links.MOVED["https://api.ibkr.com/v1/api/mcp"], links.PRESETS["ibkr"]["url"])

    def test_refusal_says_why(self):
        self.assertEqual(M._refusal(400, b'{"error":"Unsupported client","statusCode":400}'), "The server answered 400: Unsupported client.")
        self.assertEqual(M._refusal(502, b"<html>bad gateway</html>"), "The server answered 502.")

    def test_picks_monarch_tool_by_preset(self):
        tools = [{"name": "GetInvestments", "inputSchema": {"properties": {"intent": {"enum": ["budgeting", "investment_tracking"]}}, "required": ["intent"]}},
                 {"name": "UpdateTransaction"}, {"name": "GetAccounts"}]
        hold, acct = links.pick_tools(tools, links.PRESETS["monarch"])
        self.assertEqual((hold["name"], acct), ("GetInvestments", None))
        self.assertEqual(links._fill(hold), {"intent": "investment_tracking"})

    def test_never_picks_a_trading_tool(self):
        hold, _ = links.pick_tools([{"name": "place_order"}, {"name": "sell_position"}, {"name": "update_portfolio"}])
        self.assertIsNone(hold)

    def test_only_tools_named_as_reads(self):
        # a trading server's actions that a list of bad words would miss, picked first because they're shorter
        hold, _ = links.pick_tools([{"name": "close_positions"}, {"name": "exit_all_positions"}, {"name": "rebalance_portfolio"},
                                    {"name": "liquidate_holdings"}, {"name": "get_equity_positions"}])
        self.assertEqual(hold["name"], "get_equity_positions")
        self.assertIsNone(links.pick_tools([{"name": "do_positions"}, {"name": "portfolio_sweep"}])[0])
        for n in ("GetInvestments", "get_account_positions", "ListAccounts", "holdings", "PortfolioHoldings"):
            self.assertTrue(links.reads({"name": n}), n)
        self.assertTrue(links.reads({"name": "positions_v2", "annotations": {"readOnlyHint": True}}))
        self.assertFalse(links.reads({"name": "get_positions", "annotations": {"destructiveHint": True}}))

    def test_read_scope(self):
        self.assertEqual(M.read_scope(["mcp:read", "mcp:write"]), "mcp:read")
        self.assertEqual(M.read_scope(["mcp.read", "mcp.write", "mcp.orders.submit"]), "mcp.read")
        self.assertEqual(M.read_scope(["internal"]), "")


if __name__ == "__main__":
    unittest.main()
