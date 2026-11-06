"""Linked accounts: positions from a brokerage or finance app, read from its MCP server and kept in sync.

Monarch, Interactive Brokers and Robinhood have presets; any other MCP server can be linked by its address. OpenTicker
signs in once in the browser (mcp_client.py), keeps the token in the macOS Keychain, and mirrors each linked account:
a sync replaces that link's positions with what the provider reports. Positions you added yourself are never touched.

Rules that keep this safe (see AGENTS.md, Security):
- Ask for the read-only scope where the provider has one, and only ever call tools that read (`pick_tools`).
- Tokens live in the Keychain (a 0600 file off the Mac), never in the database, logs, the page or an agent.
- Connecting and disconnecting answer only this Mac; the sign-in callback must carry a state we just made.
- Provider replies are data: tickers must look like tickers, numbers must be in range, at most MAX_ROWS rows.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

import mcp_client as M
import paths
import personal

srv = None             # server.py, set by bind()
MAX_ROWS = 500
SERVICE = "dev.openticker.link"

PRESETS = {
    "monarch": {"name": "Monarch", "url": "https://api.monarch.com/mcp", "scope": "mcp:read",
                "blurb": "Every account you track in Monarch",
                "tool": "GetInvestments", "args": {"intent": "investment_tracking"}},
    "ibkr": {"name": "Interactive Brokers", "url": "https://api.ibkr.com/v1/api/mcp", "scope": "mcp.read",
             "blurb": "Straight from your broker"},
    "robinhood": {"name": "Robinhood", "url": "https://agent.robinhood.com/mcp/trading", "scope": "internal",   # its only scope
                  "blurb": "Your Robinhood account",
                  "full_access": True},
}
# other names a provider's accounts go by inside an aggregator, so the same account isn't counted twice
ALIASES = {"ibkr": ["interactive brokers", "ibkr"], "robinhood": ["robinhood"]}


def bind(server_module):
    global srv
    srv = server_module


def log(msg):
    (srv.log if srv else print)(f"links: {msg}")


# ---------------------------------------------------------------- secrets: the Keychain on a Mac, a private file elsewhere
def _keychain():
    return sys.platform == "darwin" and os.environ.get("OPENTICKER_SECRETS") != "file" and shutil.which("security")


def _secret_file(lid):
    d = paths.DATA / "links"
    d.mkdir(mode=0o700, exist_ok=True)
    return d / f"{lid}.json"


def put_secret(lid, obj):
    raw = json.dumps(obj)
    if _keychain():
        # the secret goes in on stdin as hex, so it never shows in the process list
        cmd = f"add-generic-password -U -s {SERVICE} -a {lid} -l OpenTicker -X {raw.encode().hex()}\n"
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or "error" in (r.stdout + r.stderr).lower():
            raise RuntimeError("Couldn't save the sign-in to your Keychain.")
        return
    f = _secret_file(lid)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(raw)


def get_secret(lid):
    if _keychain():
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", lid, "-w"],
                           capture_output=True, text=True, timeout=20)
        out = r.stdout.strip()
        if r.returncode != 0 or not out:
            return None
        if not out.startswith("{"):   # printed as hex when macOS thinks it isn't text
            try:
                out = bytes.fromhex(out).decode()
            except ValueError:
                return None
    else:
        f = _secret_file(lid)
        if not f.exists():
            return None
        out = f.read_text()
    try:
        return json.loads(out)
    except ValueError:
        return None


def del_secret(lid):
    if _keychain():
        subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", lid], capture_output=True, timeout=20)
    else:
        _secret_file(lid).unlink(missing_ok=True)


# ---------------------------------------------------------------- choosing tools that only read
WRITEY = re.compile(r"order|trade|buy|sell|cancel|transfer|withdraw|deposit|create|update|delete|remove|place|modify|"
                    r"submit|set_|write|allocate|merge|bulk|recategor|report", re.I)
HOLDY = re.compile(r"position|holding|portfolio|investment", re.I)
ACCTY = re.compile(r"account", re.I)


def reads(tool):
    """A tool OpenTicker may call: not named like an action, and not marked as one by the server."""
    ann = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    if ann.get("readOnlyHint") is False or ann.get("destructiveHint") is True:
        return False
    return not WRITEY.search(tool["name"])


def _required(tool):
    sch = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    props = sch.get("properties") if isinstance(sch.get("properties"), dict) else {}
    return [(k, props.get(k) if isinstance(props.get(k), dict) else {}) for k in (sch.get("required") or []) if isinstance(k, str)]


def _fill(tool, account=None):
    """Arguments for a read tool: the ones we know how to fill, or None if it needs something we can't give."""
    args = {}
    for k, spec in _required(tool):
        enum = spec.get("enum") if isinstance(spec.get("enum"), list) else []
        if k == "intent":
            args[k] = "investment_tracking" if "investment_tracking" in enum or not enum else enum[0]
        elif ACCTY.search(k) and account is not None:
            args[k] = account
        else:
            return None
    return args


def pick_tools(tools, preset=None):
    """(holdings tool, accounts tool or None) from a server's tool list, or (None, None) if none can be read safely."""
    by = {t["name"]: t for t in tools if reads(t)}
    if preset and preset.get("tool") in by:
        return by[preset["tool"]], None
    hold = [t for t in by.values() if HOLDY.search(t["name"])]
    # prefer "positions" over "portfolio summary", and tools that need nothing over ones that need an account
    hold.sort(key=lambda t: (_fill(t) is None, not re.search(r"position|holding", t["name"], re.I), len(t["name"])))
    if not hold:
        return None, None
    h = hold[0]
    if _fill(h) is not None:
        return h, None
    if _fill(h, account="x") is None:
        return None, None
    acct = sorted((t for t in by.values() if ACCTY.search(t["name"]) and not HOLDY.search(t["name"]) and _fill(t) is not None),
                  key=lambda t: len(t["name"]))
    return (h, acct[0]) if acct else (None, None)


# ---------------------------------------------------------------- reading holdings out of any reasonable reply
SYM_KEYS = ("ticker", "symbol", "ticker_symbol", "tickerSymbol", "underlying_symbol", "contractDesc")
QTY_KEYS = ("quantity", "shares", "position", "qty", "units", "share_quantity", "quantity_held")
PER_KEYS = ("avgCost", "avg_cost", "average_cost", "averageCost", "avgPrice", "avg_price", "average_price", "averagePrice",
            "average_buy_price", "cost_per_share", "costPerShare", "unit_cost", "cost_basis_per_share")
TOT_KEYS = ("cost_basis", "costBasis", "total_cost", "totalCost", "book_value", "bookValue")
KIND_KEYS = ("security_type", "securityType", "assetClass", "asset_class", "type", "instrument_type", "instrumentType", "secType")
ACCT_KEYS = ("account_name", "accountName", "account", "acctId", "accountId", "account_id", "account_number")
SKIP_KINDS = {"cash": re.compile(r"^(cash|money.?market|sweep|currency)$", re.I),
              "crypto": re.compile(r"crypto", re.I),
              "options": re.compile(r"^(opt|option|options|fop|war|warrant)$", re.I),
              "other": re.compile(r"^(bond|bonds|fixed.?income|fut|future|futures|cfd|fx|forex|cmdty|commodity|loan|other)$", re.I)}


def _num(v):
    try:
        x = float(str(v).replace(",", "").replace("$", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) < 1e13 else None


def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _records(data, depth=0):
    """Every list of dicts in the reply that looks like holdings."""
    if depth > 6:
        return []
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data) and any(_first(x, QTY_KEYS) is not None for x in data[:20]):
            return data
        return [r for x in data[:50] for r in _records(x, depth + 1)]
    if isinstance(data, dict):
        return [r for v in list(data.values())[:50] for r in _records(v, depth + 1)]
    return []


def normalize(data, account_hint=None):
    """Rows of {t, shares, cost, account} plus what was skipped and why, from a holdings reply."""
    rows, skipped = [], {"cash": 0, "crypto": 0, "options": 0, "other": [], "short": 0}
    for rec in _records(data)[:5000]:
        kind = str(_first(rec, KIND_KEYS) or "")
        why = next((k for k, rx in SKIP_KINDS.items() if kind and rx.search(kind)), None)
        sym = str(_first(rec, SYM_KEYS) or "").strip()
        if why == "other":
            skipped["other"].append(sym or kind)
            continue
        if why:
            skipped[why] += 1
            continue
        qty = _num(_first(rec, QTY_KEYS))
        if qty is None or not sym:
            if sym:
                skipped["other"].append(sym)
            continue
        per = _num(_first(rec, PER_KEYS))
        if per is None:
            tot = _num(_first(rec, TOT_KEYS))
            if tot is None and _num(rec.get("value")) is not None and _num(rec.get("variation_dollars")) is not None:
                tot = _num(rec["value"]) - _num(rec["variation_dollars"])   # Monarch: value now minus all-time gain
            per = tot / qty if tot is not None and qty else None
        split = rec.get("account_holdings")
        if isinstance(split, list):   # Monarch: one holding spread over accounts
            parts = [(str(_first(a, ACCT_KEYS) or "Other"), _num(a.get("quantity"))) for a in split if isinstance(a, dict)]
            parts = [(a, q) for a, q in parts if q]
            if not parts:
                parts = [("Other accounts", qty)]
        else:
            parts = [(str(account_hint or _first(rec, ACCT_KEYS) or ""), qty)]
        for acct, q in parts:
            if q < 0:
                skipped["short"] += 1
                continue
            rows.append({"t": sym, "shares": q, "cost": per if per is not None and per >= 0 else None, "account": acct[:120]})
    return rows, skipped


# ---------------------------------------------------------------- talking to a link
def _redirect():
    return f"http://127.0.0.1:{srv.PORT}/api/links/callback"


def _session(link, sec):
    """An open MCP session for a link, refreshing the token first if it's about to run out."""
    tok = (sec or {}).get("token") or {}
    if tok.get("expires_at") is not None and tok["expires_at"] < time.time() + 60 and tok.get("refresh_token"):
        sec["token"] = M.refresh(sec["meta"], sec["client"], tok["refresh_token"])
        put_secret(link["id"], sec)
    try:
        return M.Session(link["url"], (sec or {}).get("token", {}).get("access_token")).open()
    except M.AuthNeeded:
        tok = (sec or {}).get("token") or {}
        if not tok.get("refresh_token"):
            raise
        sec["token"] = M.refresh(sec["meta"], sec["client"], tok["refresh_token"])
        put_secret(link["id"], sec)
        return M.Session(link["url"], sec["token"]["access_token"]).open()


def fetch(link):
    """Holdings from a link's server: {"rows": [...], "skipped": {...}, "accounts": {name: count}}."""
    sec = get_secret(link["id"])
    if link.get("auth") and not sec:
        raise M.AuthNeeded()
    s = _session(link, sec)
    try:
        preset = PRESETS.get(link["provider"])
        tools = s.tools()
        hold, acct = pick_tools(tools, preset)
        if not hold:
            raise M.MCPError("This server has no tool OpenTicker can read your holdings from.")
        rows, skipped = [], {"cash": 0, "crypto": 0, "options": 0, "other": [], "short": 0}
        if acct:
            ids = _account_ids(M.tool_data(s.call_tool(acct["name"], _fill(acct))))
            for aid, name in ids[:20]:
                r, sk = normalize(M.tool_data(s.call_tool(hold["name"], _fill(hold, account=aid))), account_hint=name)
                rows += r
                _merge_skips(skipped, sk)
        else:
            args = {**(_fill(hold) or {}), **{k: v for k, v in ((preset or {}).get("args") or {}).items()
                                              if k in ((hold.get("inputSchema") or {}).get("properties") or {})}}
            rows, skipped = normalize(M.tool_data(s.call_tool(hold["name"], args)))
    finally:
        s.close()
    return clean_rows(rows, skipped)


def _merge_skips(a, b):
    for k, v in b.items():
        a[k] = a[k] + v


def _account_ids(data):
    """(id, name) for each account in an accounts tool's reply."""
    out = []

    def walk(x, depth=0):
        if depth > 5:
            return
        if isinstance(x, list):
            for y in x[:200]:
                walk(y, depth + 1)
        elif isinstance(x, dict):
            aid = _first(x, ("accountId", "account_id", "acctId", "id", "accountNumber", "account_number"))
            if aid is not None and isinstance(aid, (str, int)) and not isinstance(aid, bool):
                out.append((aid, str(_first(x, ("accountName", "account_name", "name", "displayName", "desc", "accountTitle")) or aid)))
            else:
                for v in list(x.values())[:50]:
                    walk(v, depth + 1)
        elif isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_-]{3,40}", x):
            out.append((x, x))
    walk(data)
    seen, uniq = set(), []
    for aid, name in out:
        if aid not in seen:
            seen.add(aid)
            uniq.append((aid, name))
    return uniq


def clean_rows(rows, skipped):
    """Keep tickers Yahoo has prices for; a missing cost counts gains from today's price, like the CSV import."""
    keep = []
    for r in rows[: MAX_ROWS * 4]:
        t = srv.yahoo_symbol(r["t"])
        if not srv.VALID.fullmatch(t) or not (0 < r["shares"] < 1e12) or (r["cost"] is not None and r["cost"] >= 1e9):
            skipped["other"].append(r["t"])
            continue
        keep.append({**r, "t": t})
    priced = srv.S.track_many(sorted({r["t"] for r in keep})) if keep else set()
    with srv.S.lock:
        last = {t: next((v for v in reversed(srv.S.px.get(t) or []) if v is not None), None) for t in priced}
    out = []
    for r in keep:
        if r["t"] not in priced or (r["cost"] is None and not last.get(r["t"])):
            skipped["other"].append(r["t"])
            continue
        out.append({**r, "cost": r["cost"] if r["cost"] is not None else last[r["t"]], "estimated": r["cost"] is None})
    skipped["other"] = sorted(set(skipped["other"]))[:50]
    accounts = {}
    for r in out:
        accounts[r["account"]] = accounts.get(r["account"], 0) + 1
    return {"rows": out[:MAX_ROWS], "skipped": skipped, "accounts": accounts}


# ---------------------------------------------------------------- connecting (only on this Mac)
PENDING = {}            # state -> sign-in in progress
PREVIEW = {}            # link id -> what the last fetch found, waiting for review
_lock = threading.Lock()


def connect(uid, provider, url=None, name=None):
    """Start linking. Returns {"id", "auth_url"} (open it in the browser) or {"id"} when the server needs no sign-in."""
    preset = PRESETS.get(provider)
    if preset:
        url, name = preset["url"], preset["name"]
    elif provider == "other":
        url = (url or "").strip()
        if not M.safe_url(url):
            raise ValueError("Use the server's https address, like https://example.com/mcp.")
        name = (name or "").strip()[:40] or re.sub(r"^www\.", "", urllib.parse.urlsplit(url).hostname or "MCP server")
    else:
        raise ValueError("Unknown provider.")
    if any(l["url"] == url for l in personal.links(uid)):
        raise ValueError(f"{name} is already linked. Sync it, or disconnect it first.")
    hint = M.needs_auth(url)
    lid = secrets.token_hex(8)
    if hint is None:
        personal.add_link(uid, lid, provider, name, url, auth=False)
        _fetch_async(uid, lid)
        return {"id": lid}
    meta = M.discover(url, hint or None)
    scope = preset["scope"] if preset and preset["scope"] is not None else M.read_scope(meta["scopes"])
    client = M.register(meta, _redirect(), scope)
    verifier, challenge = M.pkce()
    state = secrets.token_urlsafe(24)
    with _lock:
        for k in [k for k, v in PENDING.items() if v["at"] < time.time() - 900]:
            PENDING.pop(k)
        PENDING[state] = {"uid": uid, "lid": lid, "meta": meta, "client": client, "verifier": verifier, "at": time.time()}
    personal.add_link(uid, lid, provider, name, url, auth=True, status="signin")
    return {"id": lid, "auth_url": M.authorize_url(meta, client, _redirect(), scope, state, challenge)}


def open_browser(url):
    """Open the provider's sign-in page in the default browser on this Mac (the app's window can't host it)."""
    if sys.platform == "darwin" and url.startswith("https://") and shutil.which("open"):
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    return False


def callback(qs):
    """The browser comes back from the provider's sign-in. Returns (ok, message) for the page we show."""
    state = (qs.get("state") or [""])[0]
    with _lock:
        p = PENDING.pop(state, None)
    if not p:
        return False, "This sign-in link has expired. Go back to OpenTicker and connect again."
    link = personal.link(p["uid"], p["lid"])
    if not link:
        return False, "That link was removed. Go back to OpenTicker and connect again."
    if (qs.get("error") or [""])[0]:
        msg = "You didn't allow access." if qs["error"][0] == "access_denied" else "The provider didn't finish signing in."
        personal.update_link(p["uid"], p["lid"], status="error", error=msg)
        return False, msg
    try:
        tok = M.exchange(p["meta"], p["client"], (qs.get("code") or [""])[0], p["verifier"], _redirect())
        put_secret(p["lid"], {"meta": p["meta"], "client": p["client"], "token": tok})
    except Exception as e:
        personal.update_link(p["uid"], p["lid"], status="error", error=_msg(e))
        return False, _msg(e)
    _fetch_async(p["uid"], p["lid"])
    return True, f"OpenTicker is linked to {link['name']}."


def _msg(e):
    if isinstance(e, M.AuthNeeded):
        return "The sign-in expired. Connect again."
    if isinstance(e, (M.MCPError, ValueError, RuntimeError)):
        return str(e)
    log(f"unexpected: {e!r}")
    return "Something went wrong talking to the provider."


def _fetch_async(uid, lid):
    personal.update_link(uid, lid, status="fetching", error="")

    def run():
        link = personal.link(uid, lid)
        try:
            got = fetch(link)
            with _lock:
                PREVIEW[lid] = got
            personal.update_link(uid, lid, status="review", error="")
        except Exception as e:
            personal.update_link(uid, lid, status="auth" if isinstance(e, M.AuthNeeded) else "error", error=_msg(e))
    threading.Thread(target=run, daemon=True).start()


def preview(uid, lid):
    """What a new link found, with the accounts to leave out by default (ones another link already brings in)."""
    link = personal.link(uid, lid)
    with _lock:
        got = PREVIEW.get(lid)
    if not link or not got:
        return None
    others = [l for l in personal.links(uid) if l["id"] != lid and l["status"] == "ok"]
    words = [w for l in others for w in ALIASES.get(l["provider"], [l["name"].lower()])]
    off = [a for a in got["accounts"] if any(w in a.lower() for w in words)]
    return {**got, "off": off, "link": public(link)}


def apply(uid, lid, off=None, drop_mine=False):
    """Mirror a link into the portfolio: its positions become exactly what it reported, minus accounts left out.
    drop_mine removes positions you typed in for the same tickers, so they aren't counted twice."""
    link = personal.link(uid, lid)
    if not link:
        raise ValueError("That link is gone.")
    with _lock:
        got = PREVIEW.pop(lid, None)
    if got is None:
        raise ValueError("Nothing to add yet. Sync again.")
    off = [str(a)[:120] for a in (off if off is not None else link["off"])][:100]
    rows = [r for r in got["rows"] if r["account"] not in off]
    personal.mirror_link(uid, lid, [(r["t"], r["shares"], r["cost"], r["account"]) for r in rows], drop_mine=drop_mine)
    personal.update_link(uid, lid, status="ok", error="", off=off, synced=time.time(), count=len(rows))
    _bump()
    return len(rows)


def sync(uid, lid):
    """Fetch and mirror in one go, keeping the accounts the person chose before. Raises on failure (old positions stay)."""
    link = personal.link(uid, lid)
    if not link:
        raise ValueError("That link is gone.")
    try:
        got = fetch(link)
    except Exception as e:
        personal.update_link(uid, lid, status="auth" if isinstance(e, M.AuthNeeded) else "ok" if link["synced"] else "error",
                             error=_msg(e))
        raise ValueError(_msg(e))
    with _lock:
        PREVIEW[lid] = got
    return apply(uid, lid)


def reconnect(uid, lid):
    """A new sign-in for a link whose token expired. Keeps its positions and the accounts chosen."""
    link = personal.link(uid, lid)
    if not link:
        raise ValueError("That link is gone.")
    sec = get_secret(lid) or {}
    meta = sec.get("meta") or M.discover(link["url"], M.needs_auth(link["url"]) or None)
    client = sec.get("client") or M.register(meta, _redirect(), PRESETS.get(link["provider"], {}).get("scope", ""))
    preset = PRESETS.get(link["provider"])
    scope = preset["scope"] if preset else M.read_scope(meta["scopes"])
    verifier, challenge = M.pkce()
    state = secrets.token_urlsafe(24)
    with _lock:
        PENDING[state] = {"uid": uid, "lid": lid, "meta": meta, "client": client, "verifier": verifier, "at": time.time()}
    personal.update_link(uid, lid, status="signin")
    return {"id": lid, "auth_url": M.authorize_url(meta, client, _redirect(), scope, state, challenge)}


def disconnect(uid, lid, keep=False):
    """Forget a link: revoke its token, delete it from the Keychain, and remove its positions (or keep them as yours)."""
    link = personal.link(uid, lid)
    if not link:
        return
    sec = get_secret(lid)
    if sec and sec.get("meta") and sec.get("client"):
        tok = sec.get("token") or {}
        M.revoke(sec["meta"], sec["client"], tok.get("refresh_token") or tok.get("access_token"))
    del_secret(lid)
    with _lock:
        PREVIEW.pop(lid, None)
        for k in [k for k, v in PENDING.items() if v["lid"] == lid]:
            PENDING.pop(k)
    personal.remove_link(uid, lid, keep_positions=keep)
    _bump()


def cancel(uid, lid):
    """Give up on a link that never finished connecting."""
    link = personal.link(uid, lid)
    if link and not link["synced"]:
        disconnect(uid, lid)


def _bump():
    with srv.S.lock:
        srv.S.version += 1


def public(link):
    """What the page may see of a link: never tokens or client secrets."""
    p = PRESETS.get(link["provider"], {})
    return {"id": link["id"], "provider": link["provider"], "name": link["name"], "status": link["status"],
            "error": link["error"], "synced": link["synced"], "count": link["count"], "off": link["off"],
            "host": urllib.parse.urlsplit(link["url"]).hostname, "full_access": bool(p.get("full_access")),
            "has_preview": link["id"] in PREVIEW}


def presets():
    return [{"id": k, "name": v["name"], "blurb": v["blurb"], "full_access": bool(v.get("full_access"))} for k, v in PRESETS.items()]


# ---------------------------------------------------------------- the daily sync
def due(now, link, hours):
    """A link syncs once per trading day, 30 minutes after the close, if it hasn't since."""
    if link["status"] not in ("ok",) or not hours:
        return False
    at = dt.datetime.combine(now.date(), hours[1], tzinfo=now.tzinfo) + dt.timedelta(minutes=30)
    return now >= at and (link["synced"] or 0) < at.timestamp()


_tried = {}


def loop():
    time.sleep(90)
    while True:
        try:
            now = dt.datetime.now(srv.NY)
            hours = srv.X.session_hours(now.date())
            for uid in personal.users():
                for link in personal.links(uid):
                    if due(now, link, hours) and _tried.get(link["id"], 0) < time.time() - 3600:   # a failing link retries hourly
                        _tried[link["id"]] = time.time()
                        try:
                            n = sync(uid, link["id"])
                            log(f"synced {link['name']}: {n} positions")
                        except ValueError as e:
                            log(f"sync {link['name']} failed: {e}")
        except Exception as e:
            log(f"loop failed: {e!r}")
        time.sleep(300)
