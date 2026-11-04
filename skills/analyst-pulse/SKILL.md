---
name: analyst-pulse
description: Summarizes what Wall Street analysts think of a stock - the rating mix, price targets, recent upgrades and downgrades, and whether earnings estimates are rising or falling. Use when the user asks what analysts say, about price targets, upgrades or downgrades, or estimate revisions.
metadata:
  blurb: "Ratings, targets and estimate revisions, and their direction"
  order: 7
  label: "What analysts say"
  scope: stock
  prompt: "What are analysts saying about {t}?"
---

# What analysts say

**Data**: `openticker analysts TICKER`.

## Cover

1. **Consensus now**: the rating mix and the mean target as upside or downside. Note the spread between the lowest and highest target: a wide range means real disagreement.
2. **Direction of travel**: upgrades, downgrades and target raises or cuts over the last 30 to 60 days. Name the firms behind the most notable moves.
3. **Estimates**: whether EPS forecasts for this year and next are rising or falling, and by how much. Revisions tend to move stocks more than ratings, which are mostly buy.
4. **Leading or chasing**: is the gap between price and target closing because targets move or because the stock moves? Targets cut after a drop are chasing.

## Answer shape

Open with the direction in one line, such as "Still bullish, but targets are coming down." Then the four points, under 180 words. Use a short table only for three or more notable rating changes.

## Before you send

- "Strong buy" consensus is put in context: most ratings on most large stocks are buys.
- Firm names, dates and targets come from the data.
