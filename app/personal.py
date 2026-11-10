"""Per-user data for OpenTicker: watchlist, positions, alert rules, alert history, settings.

Everything is keyed by user_id. Today there is one local user ("me"); adding sign-in later only
means resolving a different user_id per request, not reshaping the data.

Storage is a SQLite file at data/app.db under OPENTICKER_HOME (see paths.py).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time

import paths  # noqa: E402

DATA = paths.DATA
DB_PATH = DATA / "app.db"
DEFAULT_USER = "me"

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

# AUTOINCREMENT: an alert's id never comes back after a delete (see _alert_ids_never_reused)
ALERTS = """(id integer primary key autoincrement, user_id text, kind text, t text,
    scope text, value real, active integer default 1, created real)"""
SCHEMA = f"""
create table if not exists users(id text primary key, name text, created real);
create table if not exists watch(user_id text, t text, added real, primary key(user_id, t));
create table if not exists positions(id integer primary key, user_id text, t text, shares real,
    cost real, opened text, note text, created real);
create table if not exists alerts{ALERTS};
create table if not exists events(id integer primary key, user_id text, ts real, t text, kind text,
    title text, body text, dedup text, read integer default 0, unique(user_id, dedup));
create table if not exists settings(user_id text, key text, value text, primary key(user_id, key));
create table if not exists chats(id text primary key, user_id text, title text, created real, updated real);
create table if not exists chat_msgs(id integer primary key, chat_id text, ts real, body text);
create index if not exists chat_msgs_chat on chat_msgs(chat_id, id);
create table if not exists runs(id text primary key, user_id text, chat_id text, provider text, spec text, session text,
    status text, started real, ended real, resumes integer default 0);
create index if not exists runs_status on runs(status);
create table if not exists run_events(run_id text, seq integer, kind text, body text, primary key(run_id, seq));
create table if not exists reads(id integer primary key, user_id text, t text, day text, lean text, pros integer,
    cons integer, neutral integer, line text, price real, spy real, chat_id text, created real, unique(user_id, t, day));
create table if not exists links(id text primary key, user_id text, provider text, name text, url text, auth integer,
    status text, error text, off text, synced real, count integer, created real);
"""

# Alert kinds. "scope" rules apply to a group of tickers; "t" rules to one ticker.
KINDS = {
    "move":     "Daily move of at least {value}%",
    "above":    "Price crosses above ${value}",
    "below":    "Price crosses below ${value}",
    "high52":   "New 52-week high",
    "low52":    "New 52-week low",
    "ma200":    "Crosses its 200-day average",
    "earnings": "Reports earnings today or tomorrow",
}
SCOPES = ("watch", "portfolio", "both")

DEFAULT_RULES = [
    ("move", "both", 5.0), ("high52", "both", None), ("low52", "both", None),
    ("ma200", "portfolio", None), ("earnings", "both", None),
]


def _q(sql, args=(), one=False):
    with _lock:
        cur = _conn.execute(sql, args)
        rows = cur.fetchall()
        _conn.commit()
    rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows


def _exec(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def init():
    with _lock:
        _conn.executescript(SCHEMA)
        cols = {r[1] for r in _conn.execute("pragma table_info(positions)")}
        for c in ("source", "account"):   # linked accounts (links.py): which link a position mirrors, and its account there
            if c not in cols:
                _conn.execute(f"alter table positions add column {c} text default ''")
        _conn.commit()
        _alert_ids_never_reused(_conn)
    ensure_user(DEFAULT_USER, "Me")


def _alert_ids_never_reused(c):
    """An alert's id is in its events' dedup keys ("7|AAPL|2026-11-06"), so a new alert that got a deleted one's id would
    look already fired. A database from before AUTOINCREMENT gets its alerts table rebuilt with it, ids and rows kept,
    and the counter starts above every id seen in alerts or in those keys. Safe to run on every start."""
    if "autoincrement" not in c.execute("select sql from sqlite_master where type='table' and name='alerts'").fetchone()[0].lower():
        cols = "id, user_id, kind, t, scope, value, active, created"
        try:
            c.execute("begin")
            c.execute(f"create table alerts_new{ALERTS}")
            c.execute(f"insert into alerts_new({cols}) select {cols} from alerts")
            c.execute("drop table alerts")
            c.execute("alter table alerts_new rename to alerts")
            c.execute("commit")
        except Exception:
            c.execute("rollback")
            raise
    top = c.execute("select max(m) from (select max(id) m from alerts union all select max(cast(substr(dedup, 1, instr(dedup, '|') - 1) "
                    "as integer)) from events where dedup glob '[0-9]*|*')").fetchone()[0] or 0
    c.execute("insert into sqlite_sequence(name, seq) select 'alerts', 0 where not exists (select 1 from sqlite_sequence where name='alerts')")
    c.execute("update sqlite_sequence set seq=? where name='alerts' and seq<?", (top, top))
    c.commit()


def ensure_user(uid, name=""):
    if _q("select id from users where id=?", (uid,), one=True):
        return
    _exec("insert into users(id, name, created) values(?,?,?)", (uid, name, time.time()))
    for kind, scope, value in DEFAULT_RULES:
        _exec("insert into alerts(user_id, kind, scope, value, active, created) values(?,?,?,?,1,?)",
              (uid, kind, scope, value, time.time()))


# ---------------------------------------------------------------- reads
def watchlist(uid):
    return [r["t"] for r in _q("select t from watch where user_id=? order by added", (uid,))]


def positions(uid):
    return _q("select id, t, shares, cost, opened, note, coalesce(source, '') as source, coalesce(account, '') as account "
              "from positions where user_id=? order by t, opened, id", (uid,))


def alerts(uid):
    return _q("select id, kind, t, scope, value, active from alerts where user_id=? order by id", (uid,))


def settings(uid):
    return {r["key"]: r["value"] for r in _q("select key, value from settings where user_id=?", (uid,))}


def events(uid, limit=60):
    return _q("select id, ts, t, kind, title, body, read from events where user_id=? order by ts desc limit ?",
              (uid, limit))


def unread(uid):
    return _q("select count(*) n from events where user_id=? and read=0", (uid,), one=True)["n"]


def snapshot(uid):
    s = settings(uid)
    return {
        "user": uid,
        "watch": watchlist(uid),
        "positions": positions(uid),
        "alerts": alerts(uid),
        "kinds": KINDS,
        "settings": {"ntfyTopic": s.get("ntfy_topic", ""), "ntfyServer": s.get("ntfy_server", "https://ntfy.sh"),
                     "closeNote": s.get("close_note", "on") != "off"},
        "events": events(uid),
        "unread": unread(uid),
    }


def all_symbols():
    rows = _q("select distinct t from watch union select distinct t from positions "
              "union select distinct t from alerts where t is not null")
    return sorted({r["t"] for r in rows if r["t"]})


def users():
    return [r["id"] for r in _q("select id from users")]


# ---------------------------------------------------------------- writes
def set_watch(uid, t, on):
    if on:
        _exec("insert or ignore into watch(user_id, t, added) values(?,?,?)", (uid, t, time.time()))
    else:
        _exec("delete from watch where user_id=? and t=?", (uid, t))


def add_position(uid, t, shares, cost, opened="", note=""):
    return _exec("insert into positions(user_id, t, shares, cost, opened, note, created) values(?,?,?,?,?,?,?)",
                 (uid, t, float(shares), float(cost), opened or "", note or "", time.time()))


def import_positions(uid, rows, replace=False, note="imported"):
    """Positions from a broker's file: rows of (ticker, shares, cost per share). replace clears the old ones first.
    Real positions also clear the sample portfolio, which is marked with note "sample"."""
    with _lock:
        if replace:   # your own positions; linked accounts stay as their provider reports them
            _conn.execute("delete from positions where user_id=? and coalesce(source, '')=''", (uid,))
        elif note != "sample":
            _conn.execute("delete from positions where user_id=? and note='sample'", (uid,))
        _conn.executemany("insert into positions(user_id, t, shares, cost, opened, note, created) values(?,?,?,?,?,?,?)",
                          [(uid, t, shares, cost, "", note, time.time()) for t, shares, cost in rows])
        _conn.commit()


def save_watch(uid, add=(), remove=()):
    """Apply the watchlist editor in one go: add and remove tickers together."""
    with _lock:
        _conn.executemany("delete from watch where user_id=? and t=?", [(uid, t) for t in remove])
        _conn.executemany("insert or ignore into watch(user_id, t, added) values(?,?,?)", [(uid, t, time.time()) for t in add])
        _conn.commit()


def save_positions(uid, update=(), add=(), delete=()):
    """Apply the positions editor in one go. update: (id, shares, cost, opened); add: (t, shares, cost, opened);
    delete: ids. Only this user's rows are touched."""
    with _lock:
        _conn.executemany("delete from positions where id=? and user_id=? and coalesce(source, '')=''", [(int(i), uid) for i in delete])
        _conn.executemany("update positions set shares=?, cost=?, opened=? where id=? and user_id=? and coalesce(source, '')=''",
                          [(float(sh), float(c), o or "", int(i), uid) for i, sh, c, o in update])
        _conn.executemany("insert into positions(user_id, t, shares, cost, opened, note, created) values(?,?,?,?,?,?,?)",
                          [(uid, t, float(sh), float(c), o or "", "", time.time()) for t, sh, c, o in add])
        _conn.commit()


def clear_sample(uid):
    _exec("delete from positions where user_id=? and note='sample'", (uid,))


def update_position(uid, pid, shares, cost, opened=""):
    _exec("update positions set shares=?, cost=?, opened=? where id=? and user_id=? and coalesce(source, '')=''",
          (float(shares), float(cost), opened or "", int(pid), uid))


# ---------------------------------------------------------------- linked accounts (links.py)
def _link_row(r):
    if not r:
        return None
    try:
        off = json.loads(r.get("off") or "[]")
    except ValueError:
        off = []
    return {**r, "auth": bool(r["auth"]), "off": off if isinstance(off, list) else [], "error": r.get("error") or "",
            "synced": r.get("synced"), "count": r.get("count") or 0}


def links(uid):
    return [_link_row(r) for r in _q("select * from links where user_id=? order by created", (uid,))]


def link(uid, lid):
    return _link_row(_q("select * from links where user_id=? and id=?", (uid, str(lid)), one=True))


def add_link(uid, lid, provider, name, url, auth=True, status="fetching"):
    _exec("insert into links(id, user_id, provider, name, url, auth, status, error, off, synced, count, created) "
          "values(?,?,?,?,?,?,?,?,?,?,?,?)", (lid, uid, provider, name, url, int(auth), status, "", "[]", None, 0, time.time()))


def update_link(uid, lid, **kw):
    sets, args = [], []
    for k, v in kw.items():
        if k not in ("status", "error", "off", "synced", "count", "name", "url"):
            raise ValueError(k)
        sets.append(f"{k}=?")
        args.append(json.dumps(v) if k == "off" else v)
    _exec(f"update links set {', '.join(sets)} where user_id=? and id=?", (*args, uid, str(lid)))


def remove_link(uid, lid, keep_positions=False):
    with _lock:
        if keep_positions:
            _conn.execute("update positions set source='', note='' where user_id=? and source=?", (uid, str(lid)))
        else:
            _conn.execute("delete from positions where user_id=? and source=?", (uid, str(lid)))
        _conn.execute("delete from links where user_id=? and id=?", (uid, str(lid)))
        _conn.commit()


def mirror_link(uid, lid, rows, drop_mine=False):
    """Replace a link's positions with what its provider reports now: rows of (ticker, shares, cost, account).
    Like an import, real positions clear the sample portfolio."""
    with _lock:
        _conn.execute("delete from positions where user_id=? and (source=? or note='sample')", (uid, str(lid)))
        if drop_mine:
            _conn.executemany("delete from positions where user_id=? and coalesce(source, '')='' and t=?", [(uid, t) for t in {r[0] for r in rows}])
        _conn.executemany("insert into positions(user_id, t, shares, cost, opened, note, created, source, account) values(?,?,?,?,?,?,?,?,?)",
                          [(uid, t, float(sh), float(c), "", "linked", time.time(), str(lid), acct) for t, sh, c, acct in rows])
        _conn.commit()


def add_alert(uid, kind, t=None, scope=None, value=None):
    if kind not in KINDS:
        raise ValueError("unknown alert")
    if kind in ("above", "below", "move") and value is None:
        raise ValueError("needs a value")
    if not t and scope not in SCOPES:
        raise ValueError("needs a ticker or a group")
    return _exec("insert into alerts(user_id, kind, t, scope, value, active, created) values(?,?,?,?,?,1,?)",
                 (uid, kind, t or None, None if t else scope, value, time.time()))


def set_alert_active(uid, aid, on):
    _exec("update alerts set active=? where id=? and user_id=?", (1 if on else 0, int(aid), uid))


def delete_alert(uid, aid):
    _exec("delete from alerts where id=? and user_id=?", (int(aid), uid))


def set_setting(uid, key, value):
    _exec("insert into settings(user_id, key, value) values(?,?,?) "
          "on conflict(user_id, key) do update set value=excluded.value", (uid, key, value))


def mark_read(uid):
    _exec("update events set read=1 where user_id=? and read=0", (uid,))


def has_event(uid, dedup):
    return _q("select 1 from events where user_id=? and dedup=?", (uid, dedup), one=True) is not None


def add_event(uid, t, kind, title, body, dedup):
    """Record an alert once per dedup key. Returns True if it is new."""
    with _lock:
        cur = _conn.execute("insert or ignore into events(user_id, ts, t, kind, title, body, dedup) "
                            "values(?,?,?,?,?,?,?)", (uid, time.time(), t, kind, title, body, dedup))
        _conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------- phone push (ntfy)
def push(uid, title, body, tag="chart_with_upwards_trend", click=None):
    s = settings(uid)
    topic = (s.get("ntfy_topic") or "").strip()
    if not topic:
        return False
    server = (s.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    cmd = ["curl", "-sS", "-m", "10", "-H", f"Title: {title}", "-H", f"Tags: {tag}"]
    if click:
        cmd += ["-H", f"Click: {click}"]
    cmd += ["-d", body, f"{server}/{topic}"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------- alert evaluation
def _last2(a):
    vals = [(i, v) for i, v in enumerate(a) if v is not None]
    if len(vals) < 2:
        return None, None, None
    return vals[-1][1], vals[-2][1], vals[-1][0]


def evaluate(uid, px, dates, names, earnings, link_base="", explain=None, holidays=lambda year: ()):
    """Check this user's rules against current prices. px: {t: [daily closes]}, last = today/live.
    explain(t), if given, returns a sentence on why t moved, added to price alerts. holidays(year): the exchange's
    closed days (yahoo_extra.market_holidays), so "tomorrow" is the next trading day."""
    if not dates:
        return []
    day = dates[-1]
    w, pos = set(watchlist(uid)), {p["t"] for p in positions(uid)}
    groups = {"watch": w, "portfolio": pos, "both": w | pos}
    fired = []

    def fire(rule, t, title, body, key):
        dedup = f"{rule['id']}|{t}|{key}"
        if has_event(uid, dedup):
            return
        if explain and rule["kind"] != "earnings":
            try:
                why = explain(t)
            except Exception:
                why = ""
            body = f"{body} {why}" if why else body
        if add_event(uid, t, rule["kind"], title, body, dedup):
            fired.append((t, title, body))
            push(uid, title, body, click=f"{link_base}/#{t}" if link_base else None)

    for rule in alerts(uid):
        if not rule["active"]:
            continue
        syms = [rule["t"]] if rule["t"] else sorted(groups.get(rule["scope"] or "both", ()))
        for t in syms:
            a = px.get(t)
            if not a:
                continue
            last, prev, _ = _last2(a)
            if last is None or not prev:     # a zero print would stop every alert after it
                continue
            nm = names.get(t, t)
            k, v = rule["kind"], rule["value"]
            chg = last / prev - 1
            if k == "move" and abs(chg) * 100 >= (v or 5):
                fire(rule, t, f"{t} {'+' if chg > 0 else '−'}{abs(chg) * 100:.1f}% today",
                     f"{nm} is at ${last:,.2f}, {'up' if chg > 0 else 'down'} {abs(chg) * 100:.1f}% on the day.", day)
            elif k == "above" and v and last >= v > prev:
                fire(rule, t, f"{t} crossed above ${v:,.2f}", f"{nm} is at ${last:,.2f}.", f"{day}")
            elif k == "below" and v and last <= v < prev:
                fire(rule, t, f"{t} fell below ${v:,.2f}", f"{nm} is at ${last:,.2f}.", f"{day}")
            elif k in ("high52", "low52"):
                hist = [x for x in a[-253:-1] if x is not None]
                if len(hist) < 120:
                    continue
                if k == "high52" and last > max(hist):
                    fire(rule, t, f"{t} at a 52-week high", f"{nm} hit ${last:,.2f}, above its prior high of ${max(hist):,.2f}.", day)
                if k == "low52" and last < min(hist):
                    fire(rule, t, f"{t} at a 52-week low", f"{nm} fell to ${last:,.2f}, below its prior low of ${min(hist):,.2f}.", day)
            elif k == "ma200":
                hist = [x for x in a[-201:-1] if x is not None]
                if len(hist) < 180:
                    continue
                ma = sum(hist) / len(hist)
                if (prev - ma) * (last - ma) < 0:
                    up = last > ma
                    fire(rule, t, f"{t} crossed {'above' if up else 'below'} its 200-day average",
                         f"{nm} is at ${last:,.2f}; the 200-day average is ${ma:,.2f}.", day)
            elif k == "earnings":
                e = earnings.get(t)
                if not e or not e.get("date"):
                    continue
                d = e["date"][:10]
                if d in (day, _next_day(day, holidays)) and e.get("reported") is None:
                    when = {"BMO": "before the open", "AMC": "after the close"}.get(e.get("timing"), "")
                    est = f" Analysts expect ${e['epsEst']:.2f} a share." if e.get("epsEst") is not None else ""
                    when_day = "today" if d == day else "tomorrow"
                    fire(rule, t, f"{t} reports {when_day}",
                         f"{nm} reports earnings {when_day}{' ' + when if when else ''}.{est}", d)
    return fired


def _next_day(day, holidays=lambda year: ()):
    """The trading day after day: weekends skipped, and the dates in holidays(year) (yahoo_extra.market_holidays)."""
    import datetime as dt
    d = dt.date.fromisoformat(day) + dt.timedelta(days=1)
    while d.weekday() >= 5 or d in holidays(d.year):
        d += dt.timedelta(days=1)
    return d.isoformat()


# ---------------------------------------------------------------- conversations with Tick
def chats(uid, limit=40):
    return _q("select c.id, c.title, c.updated, (select count(*) from chat_msgs m where m.chat_id=c.id) as n "
              "from chats c where user_id=? order by updated desc limit ?", (uid, limit))


def chat(uid, cid):
    c = _q("select id, title, updated from chats where id=? and user_id=?", (cid, uid), one=True)
    if not c:
        return None
    c["messages"] = [json.loads(r["body"]) for r in _q("select body from chat_msgs where chat_id=? order by id", (cid,))]
    return c


def chat_add(uid, cid, msg):
    now = time.time()
    c = _q("select user_id from chats where id=?", (cid,), one=True)
    if c and c["user_id"] != uid:
        raise PermissionError("not your conversation")
    if not c:
        title = " ".join(str(msg.get("text") or "New conversation").split())
        _exec("insert into chats(id, user_id, title, created, updated) values(?,?,?,?,?)",
              (cid, uid, title[:80] + ("…" if len(title) > 80 else ""), now, now))
    else:
        _exec("update chats set updated=? where id=?", (now, cid))
    _exec("insert into chat_msgs(chat_id, ts, body) values(?,?,?)", (cid, now, json.dumps(msg)))


def chat_drop_answer(uid, cid):
    """Asking again: take the answer after the conversation's last question off, so the new one replaces it.
    Acts only when the last message is Tick's; returns what it took, so a retry that can't start can put it back."""
    with _lock:
        c = _conn.execute("select user_id from chats where id=?", (cid,)).fetchone()
        if not c or c["user_id"] != uid:
            return []
        rows = _conn.execute("select id, body from chat_msgs where chat_id=? order by id", (cid,)).fetchall()
        tail = []
        for r in reversed(rows):
            if json.loads(r["body"]).get("role") == "user":
                break
            tail.insert(0, r)
        if not tail or len(tail) == len(rows):
            return []
        _conn.execute("delete from chat_msgs where chat_id=? and id>=?", (cid, tail[0]["id"]))
        _conn.commit()
    return [json.loads(r["body"]) for r in tail]


def chat_delete(uid, cid):
    if _q("select id from chats where id=? and user_id=?", (cid, uid), one=True):
        _exec("delete from chat_msgs where chat_id=?", (cid,))
        _exec("delete from chats where id=?", (cid,))


# ---------------------------------------------------------------- Tick's answers as logs (see runs.py)
RUN_FIELDS = {"spec", "session", "status", "ended", "resumes"}


def run_new(row):
    _exec("insert into runs(id, user_id, chat_id, provider, spec, session, status, started, resumes) values(?,?,?,?,?,?,?,?,?)",
          (row["id"], row["user_id"], row["chat_id"], row["provider"], json.dumps(row["spec"]), row["session"], row["status"],
           row["started"], row["resumes"]))
    # answers older than a month have long been saved in their conversation; their step logs can go
    old = time.time() - 30 * 86400
    _exec("delete from run_events where run_id in (select id from runs where started<? and status!='running')", (old,))
    _exec("delete from runs where started<? and status!='running'", (old,))


def run_set(rid, **kw):
    keys = [k for k in kw if k in RUN_FIELDS]
    if keys:
        _exec(f"update runs set {', '.join(k + '=?' for k in keys)} where id=?", tuple(kw[k] for k in keys) + (rid,))


def run_get(rid):
    return _q("select * from runs where id=?", (rid,), one=True)


def runs_open():
    return _q("select * from runs where status='running' order by started")


def run_events_add(rid, events):
    with _lock:
        _conn.executemany("insert or replace into run_events(run_id, seq, kind, body) values(?,?,?,?)",
                          [(rid, seq, kind, json.dumps(p)) for seq, kind, p in events])
        _conn.commit()


def run_events(rid, after=0):
    return [(r["seq"], r["kind"], json.loads(r["body"])) for r in
            _q("select seq, kind, body from run_events where run_id=? and seq>? order by seq", (rid, after))]


# ---------------------------------------------------------------- Tick's evidence checks, kept to look back on
LEANS = ("positive", "negative", "mixed")


def read_add(uid, t, lean, pros, cons, neutral, line, price, spy, day, chat_id=None):
    """One evidence check per stock per day: a second one that day replaces the first."""
    if lean not in LEANS:
        raise ValueError("lean must be positive, negative or mixed")
    _exec("insert into reads(user_id, t, day, lean, pros, cons, neutral, line, price, spy, chat_id, created) values(?,?,?,?,?,?,?,?,?,?,?,?) "
          "on conflict(user_id, t, day) do update set lean=excluded.lean, pros=excluded.pros, cons=excluded.cons, neutral=excluded.neutral, "
          "line=excluded.line, price=excluded.price, spy=excluded.spy, chat_id=excluded.chat_id, created=excluded.created",
          (uid, t, day, lean, int(pros), int(cons), int(neutral), str(line or "")[:300], price, spy, chat_id, time.time()))


def reads(uid, t=None, limit=200):
    if t:
        return _q("select * from reads where user_id=? and t=? order by day desc limit ?", (uid, t, limit))
    return _q("select * from reads where user_id=? order by day desc, t limit ?", (uid, limit))
