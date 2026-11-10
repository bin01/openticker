---
name: stock-snapshot
description: Gives a quick, plain-English take on one stock - what kind of story it is right now, how it's trading against the market, what analysts and insiders are doing, and what's coming up. Use when the user asks what's going on with a stock, wants the quick take, or names a ticker without a specific question.
metadata:
  blurb: "The story in 200 words: trend, analysts, what's next"
  order: 1
  label: "Quick take"
  scope: stock
  prompt: "Give me the quick take on {t}."
---

# Quick take

**Data**: `openticker stock TICKER`, unless it's already in the conversation.

## Write it in this order

1. **The story in one line**: name the kind of situation, such as "a momentum leader cooling off", "a cheap stock with estimates rising" or "a broken chart waiting on earnings".
2. **How it's trading**: today, 1 month and year to date against the S&P 500; where it sits against its 50- and 200-day averages; the distance from the 52-week high.
3. **What the pros think**: the consensus, the average target as upside or downside, and the direction of the last few rating and target changes. Say whether EPS estimates are rising or falling over 30 and 90 days, since revisions move stocks more than ratings do.
4. **Watch next**: the next earnings date and the move options imply; insider buying, if any; unusual options activity.
5. **If the user owns it**: one line on their position, such as its weight in the portfolio. Run `openticker portfolio` for the gain or dollar value only if they asked about it.

## Answer shape

Four or five short paragraphs or bullets, under 200 words. No headings: it's a quick take.

## Before you send

- The one-line story is backed by at least two numbers below it.
- Anything missing from the data is skipped, not guessed.
