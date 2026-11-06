"""A small MCP client for linked accounts (links.py): the Streamable HTTP transport and OAuth 2.1 sign-in with PKCE and
dynamic client registration, which is what Monarch's and Interactive Brokers' official servers speak.

Standard library only. Nothing here talks to the page: tokens come in and out as plain dicts that links.py keeps in the
Keychain. Replies from a server are untrusted, so sizes are capped and every field is read defensively.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "2025-06-18"
MAX_BODY = 8 << 20
UA = "OpenTicker"


class MCPError(Exception):
    pass


class AuthNeeded(MCPError):
    """The server wants a (new) sign-in. resource_metadata is where it says how, when it says."""

    def __init__(self, msg="Sign in again.", resource_metadata=None):
        super().__init__(msg)
        self.resource_metadata = resource_metadata


def _ctx():
    try:   # the venv's Python may not see the Mac's certificates; certifi comes with yfinance's requests
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def safe_url(url: str) -> bool:
    """https anywhere, plain http only to this machine (a server you run yourself, or the tests)."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if u.username or u.password or not u.hostname:
        return False
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))


def request(method, url, data=None, headers=None, timeout=30):
    """One HTTP request. Returns (status, headers with lower-case names, body); HTTP errors are returned, not raised."""
    if not safe_url(url):
        raise MCPError("Only https addresses can be linked.")
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read(MAX_BODY)
    except (urllib.error.URLError, OSError) as e:
        host = urllib.parse.urlsplit(url).hostname
        raise MCPError(f"Couldn't reach {host}.") from e


def _json(body):
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def _refusal(st, body):
    """'The server answered 400: Unsupported client.' with the server's own reason when it gives a short one."""
    r = _json(body)
    why = None
    if isinstance(r, dict):
        why = r.get("error_description") or r.get("message") or r.get("error")
        if isinstance(why, dict):
            why = why.get("message")
    why = re.sub(r"\s+", " ", str(why or "")).strip().rstrip(".")[:160]
    return f"The server answered {st}: {why}." if why else f"The server answered {st}."


def _bearer_meta(www_auth: str | None):
    m = re.search(r'resource_metadata="([^"]+)"', www_auth or "")
    return m.group(1) if m else None


def _sse_messages(body: bytes):
    out, data = [], []
    for line in body.decode("utf-8", "replace").splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line.strip() and data:
            msg = _json("\n".join(data))
            if msg is not None:
                out.extend(msg if isinstance(msg, list) else [msg])
            data = []
    return out


# ---------------------------------------------------------------- the protocol
class Session:
    """One MCP conversation over Streamable HTTP: initialize, list tools, call tools."""

    def __init__(self, url, token=None):
        self.url, self.token = url, token
        self.sid, self.proto, self.n, self.info = None, None, 0, {}

    def _post(self, msg):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        if self.proto:
            h["MCP-Protocol-Version"] = self.proto
        st, hd, body = request("POST", self.url, json.dumps(msg).encode(), h, timeout=60)
        if st == 401 or (st == 403 and "invalid_token" in (hd.get("www-authenticate") or "")):
            raise AuthNeeded(resource_metadata=_bearer_meta(hd.get("www-authenticate")))
        if st >= 400:
            raise MCPError(_refusal(st, body))
        if hd.get("mcp-session-id"):
            self.sid = hd["mcp-session-id"][:200]
        if "id" not in msg:
            return None
        if "text/event-stream" in (hd.get("content-type") or ""):
            replies = _sse_messages(body)
        else:
            r = _json(body)
            replies = r if isinstance(r, list) else [r] if isinstance(r, dict) else []
        for r in replies:
            if isinstance(r, dict) and r.get("id") == msg["id"]:
                if r.get("error"):
                    err = r["error"]
                    raise MCPError(str(err.get("message") if isinstance(err, dict) else err)[:300])
                return r.get("result") or {}
        raise MCPError("The server's reply didn't make sense.")

    def call(self, method, params=None):
        self.n += 1
        return self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})

    def open(self):
        r = self.call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "OpenTicker", "version": "1"}})
        self.proto = str(r.get("protocolVersion") or PROTOCOL)[:20]
        self.info = r.get("serverInfo") if isinstance(r.get("serverInfo"), dict) else {}
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tools(self):
        out, cursor = [], None
        for _ in range(10):
            r = self.call("tools/list", {"cursor": cursor} if cursor else {})
            out += [t for t in (r.get("tools") or []) if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = r.get("nextCursor")
            if not cursor:
                break
        return out

    def call_tool(self, name, args=None):
        r = self.call("tools/call", {"name": name, "arguments": args or {}})
        if r.get("isError"):
            text = " ".join(c.get("text", "") for c in (r.get("content") or []) if isinstance(c, dict))
            raise MCPError((text or f"{name} failed.")[:300])
        return r

    def close(self):
        if self.sid:
            h = {"Mcp-Session-Id": self.sid, **({"Authorization": "Bearer " + self.token} if self.token else {})}
            try:
                request("DELETE", self.url, headers=h, timeout=5)
            except MCPError:
                pass


def tool_data(result):
    """What a tool returned, as data: structured content if the server sent it, else the JSON in its text."""
    if isinstance(result.get("structuredContent"), (dict, list)):
        data = result["structuredContent"]
    else:
        data = None
        for c in result.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                d = _json(c.get("text") or "")
                if d is not None:
                    data = d
                    break
    # some servers wrap their JSON as a string inside {"result": "..."}
    for _ in range(2):
        if isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), str):
            inner = _json(next(iter(data.values())))
            if isinstance(inner, (dict, list)):
                data = inner
                continue
        break
    return data


# ---------------------------------------------------------------- sign-in (OAuth 2.1)
def _get_json(url):
    if not safe_url(url):
        return None
    try:
        st, _, body = request("GET", url, headers={"Accept": "application/json"}, timeout=15)
    except MCPError:
        return None
    d = _json(body) if st == 200 else None
    return d if isinstance(d, dict) else None


def needs_auth(url):
    """Ask the server whether it wants a sign-in. Returns its resource-metadata hint (or "") if so, None if it lets us in."""
    try:
        Session(url).open().close()
        return None
    except AuthNeeded as e:
        return e.resource_metadata or ""


def discover(url, resource_metadata=None):
    """Where and how to sign in to this MCP server, from its published metadata (RFC 9728 and RFC 8414)."""
    u = urllib.parse.urlsplit(url)
    origin, path = f"{u.scheme}://{u.netloc}", u.path.rstrip("/")
    prm = None
    for c in [resource_metadata, f"{origin}/.well-known/oauth-protected-resource{path}", f"{origin}/.well-known/oauth-protected-resource"]:
        prm = _get_json(c) if c else None
        if prm and prm.get("authorization_servers"):
            break
    prm = prm or {}
    asu = str((prm.get("authorization_servers") or [origin])[0])
    a = urllib.parse.urlsplit(asu)
    ao, ap = f"{a.scheme}://{a.netloc}", a.path.rstrip("/")
    meta = None
    for c in [f"{ao}/.well-known/oauth-authorization-server{ap}", f"{ao}/.well-known/openid-configuration{ap}",
              f"{asu.rstrip('/')}/.well-known/openid-configuration", f"{ao}/.well-known/oauth-authorization-server"]:
        meta = _get_json(c)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            break
        meta = None
    if not meta:
        raise MCPError("This server doesn't say how to sign in.")
    out = {"resource": str(prm.get("resource") or url),
           "scopes": [s for s in (prm.get("scopes_supported") or meta.get("scopes_supported") or []) if isinstance(s, str)]}
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        v = meta.get(k)
        if v and not safe_url(str(v)):
            raise MCPError("This server's sign-in isn't on https.")
        out[k] = str(v) if v else None
    return out


READ = re.compile(r"(^|[.:_/-])read(only)?$|^read", re.I)
WRITE = re.compile(r"write|order|trade|submit|transfer|admin|manage", re.I)


def read_scope(scopes):
    """The read-only scopes a server offers, space-separated, or "" when it names none."""
    return " ".join(s for s in scopes if READ.search(s) and not WRITE.search(s))


def register(meta, redirect_uri, scope=""):
    """Dynamic client registration (RFC 7591): OpenTicker introduces itself and gets a client id."""
    if not meta.get("registration_endpoint"):
        raise MCPError("This server doesn't let new apps register, so OpenTicker can't sign in to it.")
    body = {"client_name": "OpenTicker", "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none", "client_uri": "https://github.com/bin01/openticker"}
    if scope:
        body["scope"] = scope
    st, _, raw = request("POST", meta["registration_endpoint"], json.dumps(body).encode(),
                         {"Content-Type": "application/json", "Accept": "application/json"})
    d = _json(raw)
    if st not in (200, 201) or not isinstance(d, dict) or not d.get("client_id"):
        why = (d or {}).get("error_description") or (d or {}).get("error") if isinstance(d, dict) else None
        raise MCPError(f"The server wouldn't register OpenTicker{': ' + str(why)[:200] if why else ''}.")
    return {"client_id": str(d["client_id"]), "client_secret": d.get("client_secret"),
            "auth_method": d.get("token_endpoint_auth_method") or ("client_secret_post" if d.get("client_secret") else "none")}


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(meta, client, redirect_uri, scope, state, challenge):
    q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri, "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "resource": meta["resource"]}
    if scope:
        q["scope"] = scope
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return meta["authorization_endpoint"] + sep + urllib.parse.urlencode(q)


def _token(meta, client, form):
    form = {**form, "client_id": client["client_id"]}
    h = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if client.get("client_secret"):
        if client.get("auth_method") == "client_secret_basic":
            pair = f"{urllib.parse.quote(client['client_id'])}:{urllib.parse.quote(client['client_secret'])}"
            h["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form["client_secret"] = client["client_secret"]
    st, _, raw = request("POST", meta["token_endpoint"], urllib.parse.urlencode(form).encode(), h)
    d = _json(raw)
    if st != 200 or not isinstance(d, dict) or not d.get("access_token"):
        err = d.get("error") if isinstance(d, dict) else None
        if err == "invalid_grant":
            raise AuthNeeded("The sign-in expired. Sign in again.")
        raise MCPError(f"Signing in didn't work{' (' + str(err)[:80] + ')' if err else ''}.")
    return {"access_token": str(d["access_token"]), "refresh_token": d.get("refresh_token"),
            "expires_at": time.time() + float(d["expires_in"]) if isinstance(d.get("expires_in"), (int, float)) else None,
            "scope": d.get("scope")}


def exchange(meta, client, code, verifier, redirect_uri):
    return _token(meta, client, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                 "code_verifier": verifier, "resource": meta["resource"]})


def refresh(meta, client, refresh_token):
    tok = _token(meta, client, {"grant_type": "refresh_token", "refresh_token": refresh_token, "resource": meta["resource"]})
    tok["refresh_token"] = tok.get("refresh_token") or refresh_token
    return tok


def revoke(meta, client, token):
    if not meta.get("revocation_endpoint") or not token:
        return False
    form = {"token": token, "client_id": client["client_id"]}
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    try:
        st, _, _ = request("POST", meta["revocation_endpoint"], urllib.parse.urlencode(form).encode(),
                           {"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
        return st == 200
    except MCPError:
        return False
