---
name: openticker
description: Live market data and the user's own portfolio from OpenTicker, a dashboard running on their Mac. Use for any question about a stock, ETF, the market, earnings, analysts, insiders, options, or the user's watchlist and positions, and when the user mentions OpenTicker.
metadata:
  hidden: "true"
---

# OpenTicker

OpenTicker runs on the user's Mac and serves live data from Yahoo Finance plus the user's watchlist, positions and alerts. Every command prints Markdown made for you to read.

| Command | What you get |
| --- | --- |
| `openticker stock NVDA` | Company, price and trend vs the S&P 500, fund membership, analysts, earnings, insiders, options, news, events |
| `openticker analysts NVDA` | One section; also `earnings`, `ownership`, `options`, `news`, `financials`, `events` |
| `openticker portfolio` | The user's positions with P&L, watchlist, upcoming earnings, recent changes |
| `openticker brief` | What changed for the user's stocks: ratings, targets, insider trades, unusual options |
| `openticker market` | SPY, QQQ, SMH, SOXX, sector ETFs, rates, oil, dollar, VIX and the day's S&P 500 movers |
| `openticker fund SPY --h 1M` | Which holdings drove a fund over 1D, 1W, 1M, 3M, 6M or 1Y |
| `openticker compare NVDA AMD AVGO` | Side by side |
| `openticker calendar` | Earnings and economic events in the next two weeks |
| `openticker search "palantir"` | Find a ticker |

If an MCP server named `openticker` is connected, its tools return the same data; use whichever you have.

If the command isn't found, OpenTicker isn't installed. Tell the user they can install it with
`curl -fsSL https://raw.githubusercontent.com/bin01/openticker/main/install.sh | bash`. If it says the app isn't running, run `openticker start`.

## How to answer

- Lead with the answer, then the two or three numbers that support it. Numbers beat adjectives.
- Compare to something: the S&P 500, the stock's own history, its peers, or what was expected.
- Separate facts from interpretation, and say what would change the picture.
- Don't tell the user to buy or sell. Lay out the tradeoffs and what to watch.
- For a specific playbook (quick take, why it's moving, bull vs bear, earnings preview, analyst pulse, valuation, portfolio checkup, week ahead, market recap, sector rotation, macro check), use the matching `openticker-*` skill if you have it.
