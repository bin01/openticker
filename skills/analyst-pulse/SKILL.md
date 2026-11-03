---
name: analyst-pulse
description: Summarizes what Wall Street analysts are doing on a stock - ratings, price targets, estimate revisions and the direction of change. Use for "what are analysts saying about TICKER".
metadata:
  blurb: "Ratings, targets and estimate revisions, and their direction"
  order: 5
  label: "What analysts say"
  scope: stock
  prompt: "What are analysts saying about {t}?"
---

# Analyst pulse

Data: `openticker analysts TICKER`.

1. **Consensus now**: the rating mix and the mean target as upside or downside.
2. **Direction of travel**: the last 30 to 60 days of upgrades, downgrades and target raises or cuts. Name the firms behind the most notable moves.
3. **Estimates**: whether EPS forecasts for this year and next are rising or falling, and by how much. Estimate revisions often matter more than ratings.
4. **Read**: whether the analysts are chasing the price or leading it. Is the gap between price and target closing because targets move or because the stock moves?

Under 180 words.
