---
name: portfolio-checkup
description: Checks the health of the user's portfolio and watchlist - what's working, concentration, sector tilt, what changed recently and what's coming up - and raises the biggest risk as a question. Use when the user asks how their portfolio is doing, for a portfolio review, or about their own positions.
metadata:
  blurb: "What's working, concentration, risks and what's coming up"
  order: 1
  label: "Check up on my portfolio"
  scope: portfolio
  prompt: "Give my portfolio a check-up."
---

# Portfolio check-up

**Data**: `openticker portfolio` (the exact shares, cost, value and gain the scorecard needs; the data given with the question has only weights), then `openticker stock TICKER` for the one or two biggest positions or biggest movers.

## Cover

1. **Scorecard**: total value, today's move and the total gain. Name the position doing the most work and the one hurting most.
2. **Shape**: concentration (the largest position and the top three as a share of the total), sector tilt, and doubling up through similar stocks, such as owning NVDA and SMH.
3. **What changed**: the most important brief items for holdings, such as rating changes, target moves, insider trades or unusual options.
4. **Coming up**: earnings for holdings in the next two weeks, with implied moves.
5. **One thing to think about**: the biggest risk or imbalance, framed as a question, such as "NVDA is 40% of the portfolio. Is that on purpose?"

## Answer shape

Use these headings: **Scorecard**, **Shape**, **What changed**, **Coming up**, **One thing to think about**. Under 250 words. Use a small table for positions only when there are more than three.

## Before you send

- If you couldn't run `openticker portfolio`, the scorecard uses today's move in percent and the weights, and says the dollar figures weren't available.
- With no positions, review the watchlist instead, and say positions are added under My stocks, then Positions.
- The question at the end is a question, not an instruction to trade.
