---
name: portfolio-checkup
description: Health check of the user's portfolio and watchlist - concentration, sector tilt, what's driving returns, risks and upcoming events. Use for "how is my portfolio", "portfolio review".
metadata:
  blurb: "What's working, concentration, risks and what's coming up"
  order: 1
  label: "Check up on my portfolio"
  scope: portfolio
  prompt: "Give my portfolio a check-up."
---

# Portfolio check-up

Data: `openticker portfolio`, then `openticker stock TICKER` for the one or two biggest positions or biggest movers.

1. **Scorecard**: the value, today's move and the total gain. Name the position doing the most work and the one hurting most.
2. **Shape**: concentration (the largest position, the top 3), sector tilt, and anything doubling up through similar stocks.
3. **What's changed**: the most important brief items (ratings, targets, insiders, options) for holdings.
4. **Coming up**: earnings dates for holdings in the next two weeks, with implied moves where known.
5. **One thing to think about**: the biggest risk or imbalance, framed as a question rather than an instruction.

If there are no positions, review the watchlist instead and say how to add positions in the app (My stocks, then Positions).
