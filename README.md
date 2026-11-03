<p align="center"><img src="docs/icon.png" width="96" alt=""></p>

<h1 align="center">OpenTicker</h1>

<p align="center"><b>A stock market dashboard for your Mac, with your own AI agent built in.</b><br>
Live prices, what moved the S&amp;P 500 and why, your portfolio, earnings, analysts, insiders and options.<br>
Ask Claude Code, Codex, OpenCode or a local Ollama model about any of it, on the plan you already pay for.</p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-dark.png">
  <img src="docs/screenshot.png" alt="OpenTicker showing the market overview with the Ask panel open">
</picture>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/bin01/openticker/main/install.sh | bash
```

That's it. OpenTicker installs to `~/.openticker`, starts in the background, adds **OpenTicker** to your Applications and opens it. It needs macOS 12 or later; the installer sets up its own Python, so nothing else is required. (It also runs on Linux, in your browser.)

Want it on your phone too? Run `openticker start --lan`, then `openticker pair`, and open the link on your phone.

## What's inside

- **Market**: the day in plain English, then indexes, rates, the dollar, oil, the VIX and the 11 sectors.
- **Funds**: which stocks drove SPY, QQQ, SMH and SOXX over a day, a week or a year, holding by holding.
- **My stocks**: a watchlist and positions with P&L, a brief of what changed (rating changes, target moves, insider trades, unusual options), a portfolio X-ray and price alerts that reach your phone.
- **Every stock**: chart with earnings and events marked, analysts, earnings history, ownership, options positioning, financials and news.
- **Calendar and screener**: upcoming earnings and economic events; filter the S&P 500.
- **⌘K** or <kbd>/</kbd> jumps to anything. Light and dark. Installs on your phone's home screen.

## Ask your agent

Press <kbd>A</kbd> or click **Ask**. OpenTicker hands your agent the live data for what you're looking at, so answers start from real numbers, not from memory.

| Agent | Billing |
| --- | --- |
| [Claude Code](https://claude.com/claude-code) | Your Claude plan |
| [Codex](https://developers.openai.com/codex) | Your ChatGPT plan |
| [OpenCode](https://opencode.ai) | Whatever provider you signed it into |
| [Ollama](https://ollama.com) | Free, runs on your Mac |

If an agent isn't installed or signed in, Ask shows you and opens Terminal with the official one-line installer or sign-in. API keys in your environment are ignored so you're never billed twice; set `OPENTICKER_AGENT_BILLING=api` if you'd rather use them.

### Skills

One click runs a playbook written for that question. They're plain [Agent Skills](https://agentskills.io), so you can read them, edit them, or add your own in `skills/`.

| Skill | What you get |
| --- | --- |
| Quick take | The story of a stock in 200 words: trend, analysts, what's next |
| Why is it moving? | Market, sector or company news, sized against a normal day |
| Bull vs bear | Both cases from the numbers, and what would prove each right |
| Earnings preview | What's expected, how it usually reacts, what options price in |
| Analyst pulse | Ratings, targets and estimate revisions, and their direction |
| Is it expensive? | Multiples against growth, its own history and peers |
| Portfolio checkup | Concentration, sector tilt, what's driving returns, what's next |
| Week ahead | Earnings and economic data that matter for your stocks |
| Market recap | What the market did and why, in plain English |
| Which sectors lead? | Leaders and laggards across sectors, and what the shift says |
| Macro backdrop | Rates, the dollar, oil and the VIX, and what they mean for stocks |

Hover any insight and press <kbd>A</kbd> to ask about just that.

## Use it from any agent

OpenTicker's data works outside the app too, in whatever agent you already use.

**The `openticker` command** prints Markdown that agents read well:

```bash
openticker stock NVDA            # company, price and trend, analysts, earnings, insiders, options, news
openticker earnings NVDA         # one section: analysts, earnings, ownership, options, news, financials, events
openticker portfolio             # your positions, watchlist and what changed
openticker market                # indexes, sectors, macro and today's movers
openticker fund SMH --h 1M       # what drove a fund
openticker compare NVDA AMD AVGO
openticker calendar
```

**Skills for your agent**: setup installs them for Claude Code (`~/.claude/skills`) and for Codex, Cursor, OpenCode and others (`~/.agents/skills`). Re-run with `openticker skills install`. Or as a Claude Code plugin:

```
/plugin marketplace add bin01/openticker
/plugin install openticker@openticker
```

**MCP**: `openticker mcp` is a stdio MCP server with read-only tools (`stock`, `portfolio`, `market`, `fund`, `compare`, `calendar`, `search`) and the skills as prompts. For Claude Desktop, Cursor or any MCP client:

```json
{ "mcpServers": { "openticker": { "command": "openticker", "args": ["mcp"] } } }
```

## The command

```
openticker open                  open the app
openticker start [--lan|--local] run in the background and at login; --lan lets your phone connect
openticker stop | restart | status | logs
openticker pair                  link for your phone, including Ask
openticker update                pull the latest version and restart
openticker doctor                check Python, the service, the Mac app and your agents
```

## Privacy

Everything runs on your Mac. Your watchlist, positions and alerts live in `~/Library/Application Support/OpenTicker` and never leave it. Market data comes from Yahoo Finance. When you use Ask, the question and the data for what you're looking at go to the agent you chose, under that agent's terms. Only this Mac, or a phone you paired, can use Ask.

## Notes

OpenTicker uses Yahoo Finance's public data through [yfinance](https://github.com/ranaroussi/yfinance) and fund holdings published by State Street, Invesco and VanEck. It's for personal research and isn't affiliated with any of them. Data can be delayed or wrong, and nothing here is investment advice.

## Contributing

The app is a small Python server (`app/server.py`, standard library plus yfinance) and plain HTML, CSS and JavaScript (`app/index.html`, `app/static/`), with no build step. The agent layer is `app/agent.py`; the Mac app is one Swift file in `mac/`. See [AGENTS.md](AGENTS.md).

```bash
git clone https://github.com/bin01/openticker && cd openticker
./install.sh            # uses this checkout
openticker logs
```

## License

[Apache 2.0](LICENSE). Inter is by Rasmus Andersson under the [SIL Open Font License](app/static/fonts/ofl-inter.txt).
