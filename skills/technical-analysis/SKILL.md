---
name: technical-analysis
description: Reads a stock's chart in plain English - trend, moving averages, momentum (RSI, MACD), volume, volatility, support and resistance, and strength against the market and its sector. Use when the user asks about the chart, technicals, the trend, support or resistance, whether a stock is overbought or oversold, or where it might find a floor.
metadata:
  blurb: "Trend, momentum, volume, and the price levels that matter"
  order: 5
  label: "Read the chart"
  scope: stock
  data: "technicals signals"
  prompt: "Read {t}'s chart for me."
---

# Technical analysis

**Data**: `openticker technicals TICKER`, and `openticker signals TICKER` for the Screener's momentum rating and how that rating has done before. Add `openticker earnings TICKER` only to check whether earnings fall inside the next two weeks, since a report overrides any chart setup.

## Read it in this order

1. **Trend first.** The data labels it (uptrend, downtrend, pullback, bounce, mixed). Back it with where price sits against the 50- and 200-day averages and which way they slope. The 200-day is the long-term line most traders watch, so crossing it matters more than crossing the 20-day.
2. **Momentum.** RSI above 70 says the run is stretched, below 30 says the selling is. Neither is a timing signal by itself: in a strong trend RSI can stay above 70 for weeks. MACD crossing its signal line marks a turn in momentum. A cross that agrees with the trend counts for more than one against it.
3. **Volume.** It confirms or questions the move. Up days on heavier volume than down days means buyers are in control. A breakout on light volume is suspect. Call out any day above 1.5× average volume and what price did that day.
4. **Levels.** Name the nearest support below and resistance above, with their distance in %. More touches make a level stronger. Use the 52-week high and low and the 200-day as reference levels too.
5. **Relative strength.** A stock beating both the S&P 500 and its sector is a leader. One lagging both is weak even if it's rising.
6. **The momentum rating.** Say the rating in one line and whether it agrees with your read. Quote its track record only if the rating has beaten the "All" row; otherwise say it hasn't added much lately.
7. **Volatility.** Use the average true range to say what a normal day's swing is, so a level 2% away means something. Mention a Bollinger squeeze when the data flags one.

## Answer shape

- Open with one sentence that names the setup, such as "A pullback inside an uptrend, testing the 200-day at $204."
- Then three to five short bullets for trend, momentum, volume and relative strength, each with its number.
- End with **Levels to watch**: one support and one resistance, and what a close beyond each would mean.
- Draw one chart when it helps: `openticker history TICKER SPY --h 6M` as a line chart of % change.
- Keep it under 220 words.

## Before you send

- Every level and number comes from the data, not from memory.
- Signals that disagree are named as disagreeing, rather than smoothed over.
- If earnings are within two weeks, say so: the report can override the chart.
- Describe what the chart shows and what would change it. Don't call it a buy or a sell, and don't predict a price.
