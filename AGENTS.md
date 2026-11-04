# OpenTicker, for coding agents

You're probably here because someone asked you to install OpenTicker or to change it. This file is everything you need for either. Read it once, then work: the person usually isn't a developer, so make the change, check it, restart, look at it, and tell them in plain words what changed.

OpenTicker is a stock market dashboard that runs on the person's Mac: a small Python server, a plain HTML/CSS/JS page with no build step, a one-file Mac app around it, and **Tick**, an analyst panel that answers with the person's own AI agent (Claude Code, Codex, OpenCode or Ollama).

## Install it for someone

```bash
curl -fsSL https://raw.githubusercontent.com/bin01/openticker/main/install.sh | bash
```

That clones the code to `~/.openticker`, makes a private Python environment with `uv`, links `openticker` into `~/.local/bin`, starts the server in the background (and at login), builds `/Applications/OpenTicker.app` and opens it. Run `./install.sh` inside a clone instead to use that clone. Add `-s -- --lan` (or later `openticker start --lan`) to let their phone open it on the same Wi-Fi.

With Homebrew instead: `brew tap bin01/openticker https://github.com/bin01/openticker && brew install openticker`, then run `openticker` once. The Homebrew command (`packaging/homebrew/launcher.sh`, formula in `Formula/openticker.rb`) runs the same `install.sh` on first use and afterwards hands every command to `~/.openticker/bin/openticker`, so everything below applies either way.

Then run `openticker doctor`. Everything should show ✓; it also lists which AI agents Tick can use. On macOS the installer needs the Command Line Tools: if it says so, the person has to click Install in the window that opened, then you run it again.

## Change it

The loop, every time:

1. **Find the code.** `openticker status` prints where it lives (usually `~/.openticker`). Work there, or in the clone they installed from.
2. **Make the change.** The map below says where things are. Keep to the house rules at the end.
3. **Check.** `openticker check` compiles the Python, syntax-checks every script, checks that the CLI still runs on Python 3.9, validates the skills and pings the running server. Fix anything it reports.
4. **Apply.** Python changes: `openticker restart`. Page changes (HTML, CSS, JS): just reload; in the Mac app that's ⌘R. The server serves `app/` straight from disk.
5. **Look.** `openticker shot funds --dark` (or `market`, `mine`, `calendar`, `screener`, a ticker like `NVDA`; add `--phone`, `--light`, `--no-tick`) saves a screenshot with headless Chrome and prints its path. Open the image and judge it like the person would. Check light and dark, and the phone width for layout changes.
6. **Keep it.** Commit to the local repo with a plain message (`git add -A && git commit -m "Add XLE to Funds"`). `openticker update` replays their commits on top of new versions, and stops without changing anything if the two clash. Don't push anywhere unless they ask.

The person can start you here with `openticker edit "what they want"`, or from **Settings → About → Change OpenTicker** in the app.

## Where things are

| Path | What |
| --- | --- |
| `app/server.py` | The HTTP server (stdlib `ThreadingHTTPServer`): fund holdings, price history, the live price stream, alerts, the brief, and every `/api/...` route |
| `app/yahoo_extra.py` | Research data from Yahoo behind `/api/x/<name>`: analysts, financials, ownership, options, events, macro, sectors, screens |
| `app/personal.py` | SQLite: watchlist, positions, alert rules and history, settings, Tick's saved conversations |
| `app/agent.py` | Tick: the data as Markdown (`/api/agent/<cmd>`, same as the CLI), skills, the agent providers, the streamed answers, Tick's persona (`SYSTEM`) |
| `app/paths.py` | Where data lives: `OPENTICKER_HOME`, default `~/Library/Application Support/OpenTicker` (`data/`, `cache/`, `logs/`, `config.json`) |
| `app/index.html` | The page: all CSS (theme tokens at the top), the header, and the main script (funds, the stock drawer, alerts, theme) |
| `app/static/pages.js` | The router (`PAGES`) and the Market, Calendar and Screener pages |
| `app/static/stock-tabs.js` | Tabs inside the stock drawer and "What stands out" |
| `app/static/insights.js` | The brief, the portfolio X-ray, events on charts |
| `app/static/ux.js` | ⌘K command menu (`COMMANDS`) and the phone tab bar |
| `app/static/ask.js` | Tick's panel: layout, the face, menus, streaming, Markdown and charts |
| `app/static/settings.js` | The Settings sheet (gear in the header, ⌘,) |
| `bin/openticker` | The CLI: service, setup, update, data commands, `edit`/`check`/`shot`, and the stdio MCP server |
| `skills/*/SKILL.md` | Tick's playbooks (also installed for outside agents). `skills/openticker` is the hidden core skill |
| `mac/OpenTicker.swift` | The Mac app: a WKWebView window. Rebuilt by `openticker setup` and `openticker update` |

The scripts are classic `<script>` tags sharing globals, loaded in this order: the inline script in `index.html`, then `stock-tabs.js`, `insights.js`, `pages.js`, `ux.js`, `ask.js`, `settings.js`. A later file can use anything an earlier one defines. Useful globals: `base` (holdings and prices from `/api/base`), `me` (the person's data from `/api/me`), `page`, `fund`, `hz` (time range), `render()`, `load(k)`/`save(k,v)` (localStorage, prefixed `idx.`), `$`, `esc`, `ic(name,size)` with icons in `IC`, `api(path, body)` for `/api/me/...` posts.

## Recipes

**Add a fund to the Funds page** (say XLE). Add it to `FUNDS` in `app/server.py` and to `FUND_LIST` near the top of the main script in `app/index.html`. Holdings come from Yahoo's top ten automatically; for the full list, write a `holdings_xxx()` that returns `(rows, as_of, True)` from the issuer's file and add it to `HOLDING_SOURCES`. Restart, then `openticker shot funds`.

**Change how Tick talks.** Edit `SYSTEM` in `app/agent.py`. It's an f-string, so double any literal `{` `}`. Restart.

**Add a playbook** (a one-click question). Copy a folder in `skills/`, rename it, and edit the front matter: `name`, `description`, and under `metadata`: `label` (the button), `scope` (`stock`, `portfolio` or `market`), `prompt` (use `{t}` for the ticker), `blurb`, `order`. The body tells the agent how to answer, using only `openticker` commands for data. `openticker skills install` updates the copies outside agents use.

**Give Tick new data.** Add a function to `app/agent.py` that returns Markdown, wire it into `text_for()`, add the command name to `DATA_CMDS` in `bin/openticker` (and `data_query()` if it takes arguments), optionally an MCP tool in `MCP_TOOLS`, and a row in `skills/openticker/SKILL.md` so agents know it exists. Example: `history`.

**Tick's charts.** Tick writes a fenced ```` ```chart ```` block of JSON (`type` line or bar, `title`, `unit`, `x`, `series`) and `ask.js` draws it (`chartSpec`, `chartSVG`). The format is described to Tick in `SYSTEM`. A new chart type means both places.

**Add a page.** Add `[key, "Label"]` to `PAGES` in `pages.js`, a `renderKey()` that fills `#app` with an element that has an id, route it in `renderPage()`, and add that id to the `built` map in `render()` in `index.html`. Add an icon named after the key to `IC` for the phone tab bar.

**Add a setting.** Add a row in `renderSettings()` and its handler in `bindSettings()` (`app/static/settings.js`). Browser-only preferences use `save`/`load`; anything the server needs goes through `/api/me/settings` and `personal.set_setting`.

**Change colors or type.** The tokens are at the top of the `<style>` in `index.html`: `:root` for light, repeated for dark under `prefers-color-scheme` and `[data-theme="dark"]`. Change all three.

**Add an alert kind.** Add it to `KINDS` in `app/personal.py` (the text shown in the UI) and evaluate it in `alerts_loop()` in `app/server.py`.

**Change Market page sections.** `renderMarket()` in `pages.js`; macro tickers and sector ETFs are `MACRO` and `SECTOR_ETFS` in `yahoo_extra.py`.

## House rules

- **No new dependencies.** The server is the standard library plus yfinance and pandas. No frameworks, no npm, no build step.
- **`bin/openticker` runs on macOS's Python 3.9** as well as the venv: no `match`, no `X | Y` types there. `openticker check` catches this.
- **Security.** `/api/ask` answers only this Mac or a paired phone (`X-Ask-Token`), and `agent.host_ok` rejects foreign Host and Origin headers. Anything that runs an agent or a command must keep both checks (see `/api/app/terminal`). Commands come from fixed lists, never from the request.
- **Billing.** Tick never uses an API key by default (`agent.PLAN_ONLY`), so people aren't charged twice. Keep it that way.
- **Words.** UI copy is plain English for people who aren't traders: say what a number means, avoid jargon, no exclamation marks. Numbers use tabular figures; prose doesn't.
- **Look before you ship.** Every visible change gets a look in light and dark, and on a phone width if layout changed. The bar is high: clean, calm, obvious to use.
- **Data stays local.** The person's data lives in `OPENTICKER_HOME`, never in the repo. Don't commit `data/`, `cache/` or `logs/`.

## Running without the installer

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
OPENTICKER_HOME=/tmp/ot .venv/bin/python app/server.py --port 8766
```

A separate `OPENTICKER_HOME` and port keeps experiments away from the person's real data and running copy. The first start downloads holdings and a year of prices, about a minute.
