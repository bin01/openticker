---
name: insider-trades
description: Explains what a company's insiders (executives and directors) are doing with their own shares - open-market buying, selling, cluster buys, and how much of their stake they've sold - and whether it means anything. Use when the user asks about insider buying or selling, Form 4 filings, whether executives are dumping the stock, or what insiders know.
metadata:
  blurb: "Who's buying or selling, how much, and whether it means anything"
  order: 6
  label: "Insider trades"
  scope: stock
  prompt: "What are insiders doing in {t}?"
---

# Insider trades

**Data**: `openticker insiders TICKER`. For context on price and size, the trend line from `openticker stock TICKER` (already in the conversation in the app) is enough.

## How to weigh it

Most insider selling is routine and most insider buying isn't, so weigh the two differently.

- **Open-market buys are the signal.** An insider spending their own cash at market price has one reason to do it. Weigh it more when it's the CEO or CFO, when the amount is large against their pay or their stake, when several insiders buy within weeks (the data flags cluster buying), and when it follows a drop.
- **Sales are usually noise.** Executives are paid in stock and sell for taxes, diversification and pre-planned schedules (10b5-1 plans, which Yahoo doesn't flag). Selling only says something when it's unusual: several senior people at once, a large share of someone's stake (over about a quarter), a sudden change from a long habit of holding, or sales just before bad news.
- **Ignore awards, gifts and option exercises** as signals. They're pay or estate planning. Count them only to explain the totals.
- **Size matters relative to the company.** $50M of sales in a $4T company is a rounding error; in a $2B company it's not.

## Answer shape

1. **The verdict in one line**: for example, "Routine selling, no buying: nothing unusual" or "Three directors bought $4M in two weeks after the drop, the strongest insider signal in a year."
2. **The facts**: buys and sales over 90 days and 12 months, with counts, dollar totals and the number of people.
3. **Who matters**: the two or three most notable insiders, their role, what they did, and how much of their stake it was.
4. **Timing**: the price then against now, and whether trades came before earnings or a big move.
5. **What it doesn't tell you**: one line, especially on sales that may be pre-planned.

Use a small table only when more than three insiders are worth naming. Keep it under 200 words.

## Before you send

- Buys and sales are never added together as one "activity" number.
- Every name, date and amount comes from the data.
- Don't suggest the insiders know something specific. Say what the pattern has historically meant, not what will happen.
