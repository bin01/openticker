---
name: weigh-evidence
description: Weighs the evidence on a stock across six largely independent kinds (trend, estimate revisions, valuation, insiders, positioning, analysts), says which way it leans and how strongly, how the same setup has done before, and what would flip it. Use when the user asks whether to buy or sell, if it's a good time to get in or out, whether to add, trim or hold, or how much to trust a stock's setup.
metadata:
  blurb: "Six kinds of evidence, which way they lean, and how this setup has done before"
  order: 2
  label: "Weigh the evidence"
  scope: stock
  prompt: "Weigh the evidence on {t}. Which way does it lean, and how much should I trust it?"
  match: "should i (buy|sell|hold|add|trim|get in|get out)(?!.{0,30}\b(position|shares|stake)\b)|buy or sell|sell or hold|(good|right) (time|entry|price) to (buy|sell|get)|time to (buy|sell)|worth buying|weigh the evidence|how confident"
  data: "signals valuation"
---

# Weigh the evidence

**Data**: `openticker stock TICKER`, `openticker signals TICKER` and `openticker valuation TICKER` (usually in the conversation already), and `openticker reads TICKER` for earlier checks.

Confidence comes from independent kinds of evidence agreeing, not from many signals of one kind. Three trend signals that agree are one piece of evidence, not three.

## Score six kinds of evidence

Mark each one **For**, **Against** or **Neutral**, with the number behind it. If the data is missing, mark it Neutral and say "no data".

1. **Trend** (speaks to the next 1 to 3 months): the momentum rating. Buy or Strong Buy is For. Avoid is Against. Hold or Accumulate is Neutral. Name any check that failed.
2. **Estimate revisions** (3 to 12 months): this year's and next year's EPS estimates against 90 days ago, and how many analysts raised or cut in 30 days. A rise of over 2% with more raising than cutting is For; the mirror image is Against. Revisions are among the most persistent drivers of returns, because analysts adjust slowly.
3. **Valuation** (1 to 3 years): PEG, and the P/E against its own past. A PEG under about 1.5 with the P/E in the lower half of its own range is For. A PEG over about 3, or a P/E above its whole range, is Against. Valuation says little about the next month.
4. **Insiders**: open-market buys by officers or directors in 90 days are For, and cluster buying strongly so. Routine sales are Neutral. Unusual selling, such as several senior people at once or a large share of a stake, is Against.
5. **Positioning**: short interest rising while the price falls, or a put/call ratio above about 1.2 with heavy put buying, is Against. High short interest that is falling while the price rises (shorts giving up) is For. Anything else is Neutral.
6. **Analysts**: the direction of targets and ratings over 60 days, not their level, since most ratings are buys. More raises than cuts is For; more cuts than raises is Against.

## Then weigh it

- **Lean**: positive when For beats Against by 2 or more, negative when Against beats For by 2 or more, otherwise mixed. Call the lean strong only when four or more agree and neither trend nor revisions disagree.
- **Base rate**: from the signals data, say how the current rating has done 1 and 3 months later against the S&P 500, and in a market like today's (S&P 500 above or below its 200-day, and breadth). Add the stock's own record. If the rating has done no better than "All", say plainly that the trend signal hasn't added much lately.
- **Horizons**: when short- and long-term evidence disagree (a strong trend at a rich price), say which horizon each speaks to rather than averaging them.
- **Event risk**: earnings within 14 days come first. Give the date and the move options imply, since a report can override everything above.
- **What would flip it**: one or two concrete things, with a price or a date. For example, a close under the 200-day at $X, or estimate cuts after the report on DATE.
- **Earlier checks**: if `reads` shows one, say in one line which way it leaned then and how the stock has done since.
- **If they own it**: one line on the position's size and gain, and offer "Review my position" for the holding itself.

## Answer shape

1. Open with the lean and how strong it is in one sentence, such as "Leans positive, moderately: the trend and estimates agree, and valuation is the holdout."
2. A table: Evidence, Reads (For, Against or Neutral), and The number.
3. Then the base rate in two lines, the event risk, and what would flip it.
4. Optionally, one alert at the price that would flip it, in this format:

   ```alert
   {"t":"NVDA","kind":"below","value":172.50,"why":"Under here the 200-day average gives way"}
   ```

   `kind` is `above`, `below` or `ma200` (no value). The app shows it as a button, and nothing is set until the person taps it.
5. End with exactly one verdict block. The counts are out of the six kinds and add up to 6:

   ```verdict
   {"t":"NVDA","lean":"positive","for":4,"against":1,"neutral":1,"line":"The trend and estimate revisions agree; the price already asks a lot."}
   ```

   `lean` is `positive`, `negative` or `mixed`, and `line` is one sentence. The app shows it as a tally and saves it, with today's prices, to the person's record of checks.

Keep it under 300 words, not counting the blocks.

## Before you send

- Every For and Against has its number and date, and the counts in the verdict block match the table.
- Say "the evidence leans positive", never "buy". Don't predict a price.
- If the rating's track record is weak, the answer says so rather than leaning on the rating.
