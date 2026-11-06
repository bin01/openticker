"""Tick's workbench: where the agent writes and runs code to work something out.

Each conversation gets its own folder that lasts across questions, so a script written for one answer can be reused
in the next. Code runs with a Python toolbox kept apart from OpenTicker's own environment (pandas, numpy, scipy,
matplotlib, yfinance; the agent can pip install more), and `import ot` hands it OpenTicker's prices and the person's
positions without touching the server. Charts and files the code saves in out/ appear in the answer.

The sandbox is the agent's own. Claude Code runs every shell command inside macOS's sandbox (Seatbelt) with the
settings below: it can read its workbench, the toolbox and the price history but nothing else in your home folder,
and write only to its workbench and the toolbox. Its network goes through the small proxy below, which lets code
reach any public website but nothing on this Mac or its local network (so not OpenTicker's own server either).
The read-only `openticker` data commands run outside the sandbox, as before. Codex uses its own workspace-write
sandbox with the workbench as its folder and the network off: Codex's sandbox can read the whole disk and, with network,
the Keychain and OpenTicker's own server too, so its code works offline from `import ot`.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import select
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import paths

BASE = paths.HOME / "workbench"
SPACES = BASE / "spaces"                 # one folder per conversation
TOOLBOX = BASE / "python"                # the Python the agent's code runs with
CACHE = BASE / "cache"                   # pip's and matplotlib's caches, which the sandbox can write
SDK = paths.APP / "sdk"                  # `import ot`
PACKAGES = ["pandas", "numpy", "scipy", "matplotlib", "yfinance"]
KEEP_DAYS = 30

# Where code may connect if the proxy below couldn't start: Python packages, market and economic data, filings.
DOMAINS = [
    "pypi.org", "files.pythonhosted.org", "github.com", "*.github.com", "*.githubusercontent.com",
    "yahoo.com", "*.yahoo.com", "*.yimg.com",
    "sec.gov", "*.sec.gov", "fred.stlouisfed.org", "api.stlouisfed.org", "*.stlouisfed.org",
    "*.treasury.gov", "treasury.gov", "*.federalreserve.gov", "*.bls.gov", "*.bea.gov", "*.census.gov", "*.eia.gov",
    "*.data.gov", "*.cboe.com", "*.nasdaq.com", "nasdaq.com", "*.nasdaqtrader.com", "stooq.com", "*.stooq.com",
    "*.worldbank.org", "*.imf.org", "*.oecd.org", "*.ecb.europa.eu", "*.wikipedia.org", "*.wikimedia.org",
    "*.ishares.com", "*.ssga.com", "*.invesco.com", "*.vaneck.com", "*.spglobal.com", "*.cmegroup.com",
]

PROVIDERS = {"claude", "codex"}          # the agents that get a workbench
state = {"toolbox": "missing", "why": "", "failed_at": 0.0, "claude_ok": True, "claude_off": 0.0, "proxy": None,
         "serve": None}   # (OpenTicker's port, the read-only data commands) that sandboxed code may ask for through the proxy
_lock = threading.Lock()


def log(msg):
    try:
        import agent
        agent.srv.log(msg)
    except Exception:
        print(msg, file=sys.stderr)


# ---------------------------------------------------------------- the toolbox
def python():
    """The toolbox's Python, or None while it's being set up."""
    p = TOOLBOX / "bin" / "python"
    return p if p.exists() and (TOOLBOX / ".ready").exists() else None


def _uv():
    for c in (shutil.which("uv"), Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv",
              Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv")):
        if c and Path(c).exists():
            return str(c)
    return None


def _build():
    try:
        uv = _uv()
        if uv:
            subprocess.run([uv, "venv", "-q", "--allow-existing", "--python", sys.executable, str(TOOLBOX)], check=True,
                           capture_output=True, timeout=300)
            r = subprocess.run([uv, "pip", "install", "-q", "--python", str(TOOLBOX / "bin" / "python")] + PACKAGES,
                               capture_output=True, text=True, timeout=900)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(TOOLBOX)], check=True, capture_output=True, timeout=300)
            r = subprocess.run([str(TOOLBOX / "bin" / "python"), "-m", "pip", "install", "-q"] + PACKAGES,
                               capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1:] or "install failed")
        (TOOLBOX / ".ready").write_text(json.dumps({"packages": PACKAGES, "at": time.time()}))
        state.update(toolbox="ready", why="")
        log(f"Tick's workbench is ready ({', '.join(PACKAGES)})")
    except Exception as e:
        state.update(toolbox="failed", why=str(e)[:200], failed_at=time.time())
        log(f"setting up Tick's workbench failed: {e!r}")


def ensure():
    """At start-up: make the toolbox if it isn't there (in the background, a minute or two once), prune old folders,
    start the proxy."""
    for d in (SPACES, CACHE):
        d.mkdir(parents=True, exist_ok=True)
    prune()
    start_proxy()
    build()


RETRY_AFTER = 3600      # a failed toolbox install, or a sandbox that didn't start, is tried again after an hour


def build():
    """Make the toolbox in the background unless it's ready or being made. A failed install is tried again after an hour
    (the Wi-Fi may have been down), when Tick next gets a question."""
    if state["toolbox"] == "failed" and time.time() - state["failed_at"] < RETRY_AFTER:
        return
    with _lock:
        if python():
            state["toolbox"] = "ready"
            return
        if state["toolbox"] == "building":
            return
        state["toolbox"] = "building"
    threading.Thread(target=_build, daemon=True).start()


def prune():
    cut = time.time() - KEEP_DAYS * 86400
    for d in SPACES.glob("*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cut:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------- the network: any public website, nothing local
def public(host, port):
    """The addresses for host if every one of them is on the public internet, else None. Checked on every connection,
    so a name can't be pointed at this Mac or the local network."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addrs = [i[4] for i in infos]
    for a in addrs:
        ip = ipaddress.ip_address(a[0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            return None
    return addrs or None


def _pipe(a, b):
    socks = [a, b]
    try:
        while True:
            r, _, x = select.select(socks, [], socks, 120)
            if x or not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


class _Proxy(socketserver.BaseRequestHandler):
    """An HTTP proxy: CONNECT tunnels for https, plain forwarding for http. Only to public addresses."""

    def handle(self):
        c = self.request
        c.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = c.recv(4096)
                if not chunk:
                    return
                head += chunk
            line, _, rest = head.partition(b"\r\n")
            method, target, version = line.decode("latin-1").split(" ", 2)
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                body = head.split(b"\r\n\r\n", 1)[1]
            else:
                m = re.match(r"http://([^/:]+)(?::(\d+))?(/.*)?$", target)
                if not m:
                    return c.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                host, port = m.group(1), m.group(2) or "80"
                hdrs = [h for h in rest.split(b"\r\n\r\n", 1)[0].split(b"\r\n") if h and not h.lower().startswith(b"proxy-")]
                body = (f"{method} {m.group(3) or '/'} {version}\r\n".encode() + b"\r\n".join(hdrs) + b"\r\n\r\n"
                        + head.split(b"\r\n\r\n", 1)[1])
            host = host.strip("[]")
            mine = _own_data(method, host, port, target, head)
            if mine:
                return _forward_once(c, int(port), mine)
            addrs = public(host, int(port)) if port.isdigit() else None
            if not addrs:
                why = f"OpenTicker's workbench refused {host[:100]}: it is on this Mac or the local network, or it doesn't resolve. Only public websites are reachable.\n".encode()
                return c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nX-OpenTicker-Proxy: refused\r\nContent-Length: %d\r\n\r\n%s" % (len(why), why))
            up = socket.create_connection(addrs[0][:2], timeout=20)
        except (OSError, ValueError):
            try:
                c.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            return
        with up:
            if method == "CONNECT":
                c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if body:
                up.sendall(body)
            c.settimeout(None)
            up.settimeout(None)
            _pipe(c, up)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _own_data(method, host, port, target, head):
    """The one exception to "never this Mac": a plain GET for OpenTicker's own read-only data (/api/agent/<cmd> for the
    commands Tick may run), so `openticker stock NVDA` works inside the sandbox too, in a pipeline or a script.
    Returns the request to send (one request, connection closed after), or None."""
    serve = state.get("serve")
    if not serve or method != "GET" or host not in ("127.0.0.1", "localhost") or port != str(serve[0]):
        return None
    m = re.match(r"http://[^/]+(/api/agent/([a-z]+)(?:\?[^\s#]*)?)$", target)
    hdr, _, extra = head.partition(b"\r\n\r\n")
    if not m or m.group(2) not in serve[1] or extra or b"\ncontent-length" in hdr.lower() or b"\ntransfer-encoding" in hdr.lower():
        return None
    return (f"GET {m.group(1)} HTTP/1.1\r\nHost: 127.0.0.1:{serve[0]}\r\nAccept: text/plain\r\n"
            "User-Agent: openticker-workbench\r\nConnection: close\r\n\r\n").encode()


def _forward_once(c, port, req):
    """Send one request to OpenTicker and relay only the answer back; nothing else from the client reaches it."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=130) as up:
            up.sendall(req)
            while True:
                b = up.recv(65536)
                if not b:
                    break
                c.sendall(b)
    except OSError:
        pass


def start_proxy():
    if state["proxy"]:
        return state["proxy"]
    try:
        srv = _Server(("127.0.0.1", 0), _Proxy)
        state["proxy"] = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    except OSError as e:
        log(f"the workbench's proxy didn't start, so code can reach only a list of data sites: {e!r}")
    return state["proxy"]


# ---------------------------------------------------------------- a conversation's folder
def _key(key):
    k = re.sub(r"[^\w-]", "", str(key or ""))[:64]
    if not k:
        raise ValueError("no workbench for that")
    return k


def space(key, uid=None):
    """The conversation's folder, made if needed, with a fresh copy of the person's positions for `ot`."""
    d = SPACES / _key(key)
    (d / "out").mkdir(parents=True, exist_ok=True)
    os.utime(d)
    if uid is not None:
        try:
            import personal
            pos = [{k: p.get(k) for k in ("t", "shares", "cost", "opened", "note")} for p in personal.positions(uid)]
            snap = {"positions": pos, "watchlist": [w.get("t") if isinstance(w, dict) else w for w in personal.watchlist(uid)],
                    "at": time.time()}
            (d / ".openticker").mkdir(exist_ok=True)
            (d / ".openticker" / "you.json").write_text(json.dumps(snap))
        except Exception as e:
            log(f"workbench snapshot failed: {e!r}")
    return d


def find(key):
    d = SPACES / _key(key)
    return d if d.is_dir() else None


def outputs(ws, since):
    """Files the code saved in out/ during this answer: name and size, newest last."""
    out = []
    for f in sorted((Path(ws) / "out").glob("*"), key=lambda f: f.stat().st_mtime):
        try:
            st = f.stat()
            if f.is_file() and st.st_mtime >= since - 1 and st.st_size < 25_000_000 and not f.name.startswith("."):
                out.append({"name": f.name, "size": st.st_size})
        except OSError:
            pass
    return out[-12:]


def file_path(key, name):
    """A file from a conversation's out/ folder, or None. Names are plain file names, never paths."""
    if not re.fullmatch(r"[\w][\w .()+-]{0,120}", name or "") or ".." in name:
        return None
    d = find(key)
    if not d:
        return None
    p = (d / "out" / name).resolve()
    return p if p.is_file() and p.parent == (d / "out").resolve() else None


# ---------------------------------------------------------------- running agents there
def env(ws, base):
    """The agent's environment: the toolbox first on PATH, `ot` importable, caches where the sandbox can write."""
    e = dict(base)
    py = python() or (paths.ROOT / ".venv" / "bin" / "python")   # while the toolbox is being made: OpenTicker's own (pandas, numpy)
    if py.exists():
        e["PATH"] = str(py.parent) + os.pathsep + e.get("PATH", "")
        e["VIRTUAL_ENV"] = str(py.parent.parent)
    e.update(PYTHONPATH=str(SDK), MPLBACKEND="Agg", MPLCONFIGDIR=str(CACHE / "matplotlib"), PIP_CACHE_DIR=str(CACHE / "pip"),
             XDG_CACHE_HOME=str(CACHE), PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONDONTWRITEBYTECODE="1",
             OT_WORKSPACE=str(ws), OT_PRICES=str(paths.CACHE / "history.json"), OT_NAMES=str(paths.CACHE / "names.json"))
    return e


def _abs(p):
    return "/" + str(Path(p).resolve()).lstrip("/")


def claude_settings(ws):
    """Settings for Claude Code's sandbox, passed with --settings. Paths are absolute (//...)."""
    readable = [ws, TOOLBOX, CACHE, SDK, paths.ROOT, paths.CACHE / "history.json", paths.CACHE / "names.json",
                Path.home() / ".local" / "share" / "uv", Path.home() / ".claude" / "shell-snapshots"]
    py = python()
    if py:
        readable.append(Path(os.path.realpath(py)).parent.parent)       # the Python the toolbox was made from
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": ["openticker *"],
            "filesystem": {
                "allowWrite": [_abs(ws), _abs(TOOLBOX), _abs(CACHE)],
                "denyRead": ["~/"],
                "allowRead": sorted({_abs(p) for p in readable}),
            },
            # our proxy decides where code may go (any public site); without it, a list of data sites
            "network": {"httpProxyPort": state["proxy"], "allowedDomains": [], "allowLocalBinding": False} if state["proxy"]
            else {"allowedDomains": DOMAINS, "allowLocalBinding": False},
        },
        "permissions": {"blockWritesOutsideWorkingDirectories": True},
        "disableAllHooks": True,      # the person's own hooks and plugins (say one that redirects WebFetch) aren't Tick's
    }


def claude_tools(ws, data_cmds):
    """Tools for Claude Code in its workbench, and what it may use without asking."""
    w = _abs(ws)
    allowed = [f"Bash(openticker {c}:*)" for c in data_cmds] + [f"Edit(/{w}/**)", f"Write(/{w}/**)", f"Read(/{w}/**)",
                                                               "Glob", "Grep", "WebSearch", "WebFetch"]
    return ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"], allowed


def codex_args(ws):
    return ["--add-dir", str(TOOLBOX), "--add-dir", str(CACHE)]   # the folder itself is Codex's working folder


def claude_ready():
    """Whether Claude Code gets a workbench. After its sandbox failed to start, it answers without one for an hour, then
    tries again (Claude Code may have been updated since)."""
    if not state["claude_ok"] and time.time() - state["claude_off"] > RETRY_AFTER:
        state["claude_ok"] = True
    return state["claude_ok"]


def claude_failed():
    state.update(claude_ok=False, claude_off=time.time())


def sandbox_failed(text):
    """Whether an agent's error says its sandbox couldn't start, so the answer is retried without the workbench."""
    return bool(re.search(r"sandbox", text or "", re.I)) and bool(re.search(r"unavailable|not available|fail|could ?n.t|unable|error", text or "", re.I))


def note(offline=False):
    """The workbench note for the prompt. Until the toolbox is ready, code runs on OpenTicker's own Python, which has
    pandas, numpy and yfinance but not scipy or matplotlib, so the note says so instead of promising them. Offline (Codex,
    whose sandbox has no network) it says code can't download anything or install packages."""
    out = NOTE if python() else NOTE.replace(_TOOLS_LINE, _TOOLS_LINE_EARLY).replace(
        "- To show a chart from code,", "- Once the toolbox is ready, to show a chart from code,")
    if offline:
        out = out.replace(_TOOLS_LINE, _TOOLS_LINE_OFFLINE).replace(_TOOLS_LINE_EARLY, _TOOLS_LINE_OFFLINE)
        out = "\n".join(ln for ln in out.split("\n") if not ln.startswith("- Some sites refuse scripts"))
        out = out.replace("  For anything else, use the `openticker` commands or yfinance.", "  Prices for other tickers aren't available offline.")
    return out


_TOOLS_LINE = ("- `python3` has pandas, numpy, scipy, matplotlib and yfinance; `pip install` more if you need it. Code can download "
               "from any public website (filings, economic data, CSVs), but nothing on this Mac or its local network.")
_TOOLS_LINE_EARLY = ("- The Python toolbox is still being set up, so `python3` has only pandas, numpy and yfinance for now: no scipy, "
                     "no matplotlib and no `pip install`. Charts from code aren't possible yet, so use a ```chart block. Code can "
                     "download from any public website (filings, economic data, CSVs), but nothing on this Mac or its local network.")

_TOOLS_LINE_OFFLINE = ("- `python3` has pandas, numpy and, once the toolbox is ready, scipy and matplotlib. Your sandbox has no network: "
                       "code can't download anything or install packages, so work from `import ot` and the data above.")

NOTE = """You have a workbench: your current folder belongs to this conversation and keeps its files between questions.
Use it whenever an answer needs real math (returns, volatility, drawdowns, correlation, beta, a backtest, a what-if on the person's positions): write a short Python script, run it, and read what it prints. Don't do multi-step arithmetic in your head.
""" + _TOOLS_LINE + """
- `import ot` gives OpenTicker's data without a network call:
  ot.prices(["NVDA", "SPY"])  daily closes, a DataFrame (dates down, tickers across), about two years, for ~1,100 stocks and ETFs; others come from Yahoo
  ot.returns(["NVDA", "SPY"])  daily returns of the same
  ot.positions()  the person's positions (t, shares, cost); ot.watchlist()  their watchlist
  ot.style()  call before plotting so charts match the app
  For anything else, use the `openticker` commands or yfinance.
- Some sites refuse scripts that don't say who they are. SEC EDGAR (sec.gov, data.sec.gov) does, so fetch from it with ot.get(url) or ot.get_json(url), which send a declared user agent and keep under SEC's 10 requests a second; set the same User-Agent header if you use another library. A 403 that says "OpenTicker's workbench refused" means the address is local, not that the site blocked you.
- To show a chart from code, save it as a PNG in out/ (plt.savefig("out/nvda-drawdown.png")) and put ![short title](out/nvda-drawdown.png) where it belongs in your answer. For a simple line or bar chart, the ```chart block is still better. Anything else you save in out/ (a CSV, say) is offered to the person as a download; mention it.
- Every command runs inside the sandbox, and a request to run one outside it is refused. Write longer code to a .py file and run `python3 file.py`.
- Keep scripts small and print only what you need. Never print the code itself in the answer unless asked."""
