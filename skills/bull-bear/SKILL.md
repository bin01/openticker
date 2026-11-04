---
name: bull-bear
description: Lays out a balanced bull case and bear case for a stock, each point tied to a number, plus what would settle the debate and where the market already leans. Use when the user asks for the bull and bear case, what could go wrong, whether to worry about a stock, or the risks and upside.
metadata:
  blurb: "Both sides, each tied to a number, and what settles it"
  order: 6
  label: "Bull vs bear"
  scope: stock
  prompt: "Lay out the bull and bear case for {t}."
---

# Bull vs bear

**Data**: `openticker stock TICKER` and `openticker financials TICKER` for the growth and margin trend. Add `openticker technicals TICKER` if the trend is part of either case.

## Build each side

- **Bull case**: three points, each tied to a number. Good sources: revenue growth and its direction, margin trend, rising estimates, target upside, insider buying, relative strength.
- **Bear case**: three points, each tied to a number. Good sources: valuation against growth, slowing revenue, estimate cuts, unusual insider selling, crowded positioning, a broken trend.
- **What settles it**: the one or two things that would prove either side right, with dates where possible, such as the next earnings or guidance.
- **Where the market leans**: whether the price, consensus and positioning already favor one side. A crowded bull case leaves less room for upside.

## Answer shape

Use these headings: **The bull case**, **The bear case**, **What settles it**, **Where the market leans**. Make each point one line. Under 250 words.

## Before you send

- Both sides get the same number of points, with the same level of evidence.
- The answer doesn't end with a call to buy or sell.
