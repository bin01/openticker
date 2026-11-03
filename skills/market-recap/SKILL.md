---
name: market-recap
description: Plain-English recap of what the stock market did today or over a period and why, with the stocks and macro moves behind it. Use for "what happened in the market today", "market recap".
metadata:
  blurb: "What moved the index today and why"
  order: 1
  label: "Market recap"
  scope: market
  prompt: "What happened in the market today?"
---

# Market recap

Data: `openticker market`, and `openticker fund SPY` for today's drivers (add `--h 1W` or `--h 1M` for longer windows).

1. **Headline**: the index moves in one sentence, and whether it was broad or driven by a few large stocks. Compare the equal-weight average with the index.
2. **Drivers**: the stocks that moved the index most, with their contribution.
3. **Macro**: the moves in rates, the dollar, oil, gold, bitcoin and the VIX, and whether they explain the day.
4. **Read-through**: what the day says about leadership (tech or not, risk-on or risk-off).

If you can search the web, add the main news catalyst. Otherwise say the data shows what moved, not why.
