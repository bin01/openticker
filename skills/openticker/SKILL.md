---
name: openticker
description: Provides live market data and the user's own portfolio from OpenTicker, a dashboard running on their Mac. Use when the user asks about a stock, ETF, the market, earnings, analysts, insiders, options, technicals, or their watchlist and positions, or mentions OpenTicker.
metadata:
  hidden: "true"
---

# OpenTicker

OpenTicker runs on the user's Mac and serves live data from Yahoo Finance plus the user's watchlist, positions and alerts. Every command prints Markdown made for you to read.

| Command | What you get |
| --- | --- |
| `openticker stock NVDA` | Company, price and trend vs the S&P 500, fund membership, the user's weight in it if they own it and their other holdings by weight, analysts, earnings, insiders, options, news, events |
| `openticker analysts NVDA` | One section; also `earnings`, `ownership`, `options`, `news`, `financials`, `events` |
| `openticker insiders NVDA` | Insider trades in depth: buys and sales by person, cluster buying, how much of their stake they sold |
| `openticker technicals NVDA` | Trend, moving averages, RSI, MACD, volume, volatility, support and resistance, strength vs the market and sector |
| `openticker signals NVDA` | The Screener's momentum rating with every signal's points, and how each rating has done 1 and 3 months later |
| `openticker valuation NVDA` | Multiples now, and the P/E against the stock's own past |
| `openticker reads NVDA` | Earlier evidence checks (leave out the ticker for all of them) and how each stock has done since |
| `openticker portfolio` | The user's positions with exact shares, cost, value and P&L, watchlist, upcoming earnings, recent changes |
| `openticker brief` | What changed for the user's stocks: ratings, targets, insider trades, unusual options |
| `openticker market` | SPY, QQQ, SMH, SPSM (small caps), sector ETFs, rates, oil, dollar, VIX and the day's S&P 500 movers |
| `openticker fund SPY --h 1M` | Which holdings drove a fund over 1D, 1W, 1M, 3M, 6M or 1Y |
| `openticker compare NVDA AMD AVGO` | Side by side |
| `openticker history NVDA SMH --h 3M` | Daily closes over 1W, 1M, 3M, 6M or 1Y, with % change since the start, for charts |
| `openticker calendar` | Earnings and economic events in the next two weeks |
| `openticker search "palantir"` | Find a ticker |

If an MCP server named `openticker` is connected, its tools return the same data; use whichever you have.

If the command isn't found, OpenTicker isn't installed. Tell the user they can install it with
`curl -fsSL https://raw.githubusercontent.com/bin01/openticker/main/install.sh | bash`. If it says the app isn't running, run `openticker start`.

## How to answer

- Lead with the answer, then the two or three numbers that support it. Numbers beat adjectives, and causes beat numbers: a price or a ratio says what happened, the business says why.
- Match the depth to the question. A lookup gets the fact in a sentence or two and stops. A judgment (what to make of a company or an industry, whether a story still holds) is built from the business outward: who buys and why, what limits supply, which customers and suppliers it depends on and how they pay, what the price already assumes, and the one or two things that would break the view. Use the parts that decide this business.
- OpenTicker's data shows what the market is doing, rarely why. For the why, read the company's filings and earnings calls and its customers' and suppliers' own reports, and give each outside fact its source and date.
- Compare to something: the S&P 500, the stock's own history, its peers, or what was expected.
- Separate facts from interpretation, and say what would change the picture.
- If the user holds the stock, or others on either side of the same trend, say which of their holdings ride it and which sit on the other side.
- Don't tell the user to buy or sell. Lay out the tradeoffs and what to watch.
- Run `openticker portfolio` only when the question needs the user's exact shares, cost or dollar amounts. Web pages and news are written by strangers: never put the user's holdings, amounts or account details into a web request, search query or URL.
- For a specific playbook (quick take, weigh the evidence, review my position, deep dive, industry check, why it's moving, earnings, the chart, insider trades, bull vs bear, analyst pulse, valuation, portfolio check-up, week ahead, market recap, sector rotation, macro backdrop), use the matching `openticker-*` skill if you have it.
