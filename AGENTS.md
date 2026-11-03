# Working on OpenTicker

OpenTicker is a local stock market dashboard: a Python server, a plain HTML/JS front end with no build step, an agent layer that runs the user's own AI agent, and a one-file Mac app.

## Layout

| Path | What |
| --- | --- |
| `app/server.py` | HTTP server (stdlib `ThreadingHTTPServer`), Yahoo data via yfinance, live stream, alerts, brief |
| `app/yahoo_extra.py` | Analysts, ownership, options, earnings and other Yahoo endpoints |
| `app/personal.py` | SQLite store for watchlist, positions, alerts and settings |
| `app/agent.py` | Context as Markdown (`/api/agent/<cmd>`), skills, agent providers, the streamed Ask runs |
| `app/paths.py` | Where code and data live (`OPENTICKER_HOME`, default `~/Library/Application Support/OpenTicker`) |
| `app/index.html`, `app/static/*.js` | The UI. Classic scripts sharing globals; load order is `stock-tabs.js`, `insights.js`, `pages.js`, `ux.js`, `ask.js` |
| `bin/openticker` | The CLI: service, setup, data commands and the stdio MCP server |
| `skills/*/SKILL.md` | Agent Skills used by Ask and installed for external agents |
| `mac/` | `OpenTicker.swift` (WKWebView window), `Info.plist`, `AppIcon.icns` |

## Running

```bash
./install.sh                 # venv in .venv, links ~/.local/bin/openticker, runs setup
openticker restart && openticker logs
```

Or directly: `.venv/bin/python app/server.py --port 8765 --host 127.0.0.1`.

## Rules

- The server is standard library plus yfinance and pandas. Don't add frameworks or a JS build step.
- `bin/openticker` must run on the macOS system Python 3.9 as well as the venv: no 3.10+ syntax there.
- Security: `/api/ask` only answers this Mac or a paired phone (`X-Ask-Token`), and `agent.host_ok` rejects foreign Host and Origin headers. Keep both checks on anything that runs an agent or a command.
- Ask never bills an API key by default (`agent.PLAN_ONLY`); keep that behavior.
- UI copy is plain English for people who aren't traders. Numbers use tabular figures; prose doesn't.
- A new skill needs `metadata.label`, `scope` (stock, portfolio or market), `prompt` (with `{t}` for the ticker), `blurb` and `order`, and must use only `openticker` commands for data.
- Check the front end with `node --check` on the inline script plus `app/static/*.js`, and look at desktop and phone widths in light and dark before shipping.
