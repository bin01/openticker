"""Support and resistance levels from price bars (5-minute up to quarterly). Standard library only, so the Levels page (yahoo_extra.levels),
Tick's technicals (agent.sec_technicals) and the tests all share one definition."""


def key_levels(h, l, c, d, look=252, w=5, tol=None, min_pct=0.006, recent=63):
    """Support and resistance from swing points over the last `look` bars (a year of daily bars by default): a bar whose high (low) is the highest (lowest)
    of the w bars on each side. Swings within `tol` (as a share of the latest price) of each other are one level, drawn as a zone from the
    lowest to the highest swing in it. More touches, and recent ones, make a level stronger. A level that was hit
    from both sides (a swing high and a swing low) has flipped roles, which traders watch closely."""
    n = len(c)
    if tol is None:
        tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(max(1, n - 14), n)]
        atr = sum(tr) / len(tr) if tr else 0
        # about half a normal bar's range, never tighter than min_pct (0.6% on daily bars) nor wider than four times it
        tol = min(max(0.6 * atr, min_pct * c[-1]), 4 * min_pct * c[-1])
    rel = tol / c[-1]       # zones are a share of price, so years of weekly or quarterly bars group fairly at any price
    pts = []
    for i in range(max(w, n - look), n - w):
        if h[i] == max(h[i - w:i + w + 1]):
            pts.append((h[i], i, "hi"))
        if l[i] == min(l[i - w:i + w + 1]):
            pts.append((l[i], i, "lo"))
    pts.sort()
    groups = []
    for p, i, k in pts:
        if groups and p <= groups[-1][0][0] * (1 + rel):
            groups[-1].append((p, i, k))
        else:
            groups.append([(p, i, k)])
    out = []
    for g in groups:
        wts = [1 + i / n for _, i, _ in g]      # recent swings count a little more toward where the level sits
        px = sum(p * x for (p, _, _), x in zip(g, wts)) / sum(wts)
        last_i = max(i for _, i, _ in g)
        kinds = {k for _, _, k in g}
        fresh = n - 1 - last_i <= recent
        score = len(g) + (1 if fresh else 0) + (1 if len(kinds) == 2 else 0)
        out.append({"p": round(px, 4), "lo": round(min(p for p, _, _ in g), 4), "hi": round(max(p for p, _, _ in g), 4),
                    "touches": len(g), "last": d[last_i], "ago": n - 1 - last_i, "flip": len(kinds) == 2,
                    "strength": 3 if score >= 5 else 2 if score >= 3 else 1})
    return out, tol


def nearest(lv, last, tol, keep=3, far=None):
    """The levels nearest the price on each side, closest first, plus any the price is sitting on. A level within half
    the zone width of the price is where it trades now, not above or below. One-touch swings are mostly noise, so
    they're kept only when they are the nearest on their side, so a side is never empty while there's a swing there.
    `far` drops levels more than that share of the price away."""
    room = tol / 2
    if far:     # a level this far away (as a share of price) says nothing about where the price is now
        lv = [x for x in lv if abs(x["p"] / last - 1) <= far]
    above = sorted([x for x in lv if x["p"] > last + room], key=lambda x: x["p"])
    below = sorted([x for x in lv if x["p"] < last - room], key=lambda x: -x["p"])
    pick = lambda side: [x for i, x in enumerate(side) if x["touches"] >= 2 or i == 0][:keep]
    return {"resistance": pick(above), "support": pick(below),
            "here": [x for x in lv if abs(x["p"] - last) <= room and x["touches"] >= 2]}
