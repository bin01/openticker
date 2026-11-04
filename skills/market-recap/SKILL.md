---
name: market-recap
description: Recaps what the stock market did today or over a period and why, in plain English - the index moves, whether it was broad or driven by a few giants, the stocks behind it and the macro moves. Use when the user asks what happened in the market, for a market recap, or why stocks are up or down.
metadata:
  blurb: "What moved the index today and why"
  order: 1
  label: "Market recap"
  scope: market
  prompt: "What happened in the market today?"
---

# Market recap

**Data**: `openticker market`, and `openticker fund SPY` for today's drivers. Add `--h 1W` or `--h 1M` for a longer window.

## Cover

1. **Headline**: the index moves in one sentence, and whether it was broad or carried by a few large stocks. Compare the average stock with the index. When they differ by more than half a point, size, not breadth, drove the day.
2. **Drivers**: the stocks that moved the index most, with their contribution in points.
3. **Macro**: rates, the dollar, oil, gold, bitcoin and the VIX, and whether they explain the day.
4. **Read-through**: what it says about leadership, such as tech or not, and risk-on or risk-off.

## Answer shape

Open with the headline sentence, then a short paragraph or bullets for the rest. Under 200 words. A bar chart of the top contributors helps when one or two stocks dominate.

## Before you send

- If you can search the web, add the main news catalyst. Otherwise say the data shows what moved, not why.
