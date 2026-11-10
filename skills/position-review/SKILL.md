---
name: position-review
description: Reviews a stock the user owns - where they stand, what changed since they bought, whether the evidence still holds, how much they could lose to the next support or stop in dollars, how big it is in the portfolio, and what's coming up - with alerts offered at the prices that matter. Use when the user asks whether to sell, trim, hold or add to something they own, take profits, cut a loss, or review a position.
metadata:
  blurb: "What changed since you bought, the risk in dollars, and the prices to watch"
  order: 3
  label: "Review my position"
  scope: stock
  prompt: "Review my position in {t}."
  match: "(sell|trim|take profits?|cut (my )?loss|hold on to|keep holding|review|add to) .{0,30}(position|shares|stake)|my (position|shares|stake) in"
  data: "signals technicals"
---

# Review my position

**Data**: `openticker stock TICKER` (it has the position, each purchase, and the share of the portfolio), `openticker signals TICKER` and `openticker technicals TICKER` (usually in the conversation already). Add `openticker reads TICKER` for earlier checks and `openticker portfolio` when concentration matters.

If the user doesn't own the stock, say so in one line and weigh the evidence instead, as the "Weigh the evidence" playbook does.

## Work through

1. **Where you stand**: shares, average cost, gain in dollars and percent, and the share of the portfolio. For each dated purchase, how the stock has done since against the S&P 500. Beating the market is the real test, since an index fund was the alternative.
2. **What changed since you bought**: the momentum rating then and now (the purchase lines give it when the record reaches back), estimates and targets, and the trend. Name the one change that matters most.
3. **Does the evidence still hold**: a short version of the six kinds (trend, estimate revisions, valuation, insiders, positioning, analysts), with only the ones that changed or that disagree.
4. **Risk from here, in dollars**: the nearest support and the momentum method's stop, each as a price, a distance in percent, and what the position would lose getting there. Use the average true range to say what a normal day's swing costs. Dollars make risk concrete in a way percentages don't.
5. **Size**: above about 10% of the portfolio, one stock's bad quarter becomes the portfolio's bad quarter. Say the share plainly, and whether it grew there by rising.
6. **Coming up**: the next earnings date and the move options imply, also in dollars for this position.

## Answer shape

- Open with one sentence that sums it up, such as "Up 42% since March and now 18% of the portfolio; the trend holds, but estimates have started to slip."
- Then short sections: **Where you stand**, **What changed**, **Risk from here**, **Coming up**.
- End with **Prices to watch**: one or two, each as an alert block, for example:

  ```alert
  {"t":"NVDA","kind":"below","value":172.50,"why":"Nearest support; the position would be down $2,400 from today"}
  ```

  `kind` is `above`, `below` or `ma200` (no value). The app shows each as a button, and nothing is set until the person taps it.
- If the choice is close, end with the question it comes down to, such as "Is 18% in one stock on purpose?"
- Keep it under 280 words, not counting the alert blocks.

## Before you send

- Dollar figures come from the person's own shares and the prices in the data. Show the arithmetic once if it isn't obvious.
- No instruction to sell, trim or add. Lay out the tradeoff and what would change it, without announcing that you won't decide for them: the first line is the summary.
- If the gain is large, add one line that taxes may matter and depend on how long they've held it and where they live.
