---
name: stock-snapshot
description: Quick, plain-English take on a single stock - what the company is, how the stock is doing, what analysts and insiders are doing, and what's coming up. Use when someone asks "what's going on with TICKER" or "give me the quick take".
metadata:
  blurb: "The story in 200 words: trend, analysts, what's next"
  order: 1
  label: "Quick take"
  scope: stock
  prompt: "Give me the quick take on {t}."
---

# Stock snapshot

Get the data with `openticker stock TICKER` unless it is already in front of you.

Write it in this order:
1. **One-line verdict**: what kind of story this stock is right now. Examples: "a momentum leader cooling off", "a value name with estimates rising", "a broken chart waiting on earnings".
2. **How it's trading**: today, 1 month and YTD versus the S&P 500, where it sits against its 50 and 200-day averages, and its distance from the 52-week high.
3. **What the pros think**: the consensus, the average target as upside or downside, and the direction of the last few rating or target changes. Say whether EPS estimates are rising or falling over 30 and 90 days.
4. **Watch next**: the next earnings date and the move options imply, any insider buying, and unusual options.
5. If the user owns it, one line on what it means for their position, such as its size or gain.

Keep it under 200 words. Use numbers, not adjectives.
