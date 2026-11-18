---
name: bull-bear
description: Lays out a balanced bull case and bear case for a stock, each point tied to a number, plus what would settle the debate and where the market already leans. Use when the user asks for the bull and bear case, what could go wrong, whether to worry about a stock, or the risks and upside.
metadata:
  blurb: "Both sides, each tied to a number, and what settles it"
  order: 7
  label: "Bull vs bear"
  scope: stock
  prompt: "Lay out the bull and bear case for {t}."
---

# Bull vs bear

**Data**: `openticker stock TICKER` and `openticker financials TICKER` for the growth and margin trend. Add `openticker technicals TICKER` if the trend is part of either case. For the business points, read the latest earnings call or annual report if you can reach the web; otherwise use what you know of the industry and say it's from memory.

## Build each side

Each case stands on the business first and the market's numbers second. A case made only of ratios and price trends describes the stock, not the company, and both sides can quote the same chart.

- **Bull case**: three points, each tied to a number. At least one, ideally two, is about the business: demand that is growing or shifting its way, a supply limit that protects its prices, customers it's winning. The rest can come from the numbers: revenue growth and its direction, margin trend, rising estimates, insider buying, relative strength.
- **Bear case**: three points, each tied to a number. At least one, ideally two, is about the business: reliance on a few customers, buyers who could make it themselves or switch, new capacity that will push prices down, spending by its customers that depends on borrowed money. The rest can come from the numbers: valuation against growth, slowing revenue, estimate cuts, unusual insider selling, crowded positioning, a broken trend.
- **What settles it**: the one or two things that would prove either side right, with dates where possible. Prefer evidence from the business (what a big customer says about next year's spending, a price along the supply chain) over "the next earnings".
- **Where the market leans**: whether the price, consensus and positioning already favor one side. A crowded bull case leaves less room for upside.

## Answer shape

Use these headings: **The bull case**, **The bear case**, **What settles it**, **Where the market leans**. Make each point one or two lines. Under 300 words.

## Before you send

- Both sides get the same number of points, with the same level of evidence.
- Each side has a point about the business that would still be true if the share price were hidden.
- The answer doesn't end with a call to buy or sell.
