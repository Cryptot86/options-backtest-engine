#!/usr/bin/env python
"""BOOK-LEVEL CIRCUIT BREAKER test — after N consecutive losing exits across the
stock book, pause ALL new stock entries for K days. Does it improve the curve?

Baseline = gated stock book (VIX or name gate), 1 contract, dedupe (1/name +
2/day) + the 21-day SAME-NAME cooldown (now law). Breakers layered on top.
Consecutive losses counted in EXIT order, reset by any winning exit.
Also tests SIGNAL RANKING: on days with >2 candidates, take the best 2 by VRP
instead of the first 2 (efficiency idea, mechanism: richer premium = better pay).
"""
from __future__ import annotations
import pandas as pd, numpy as np

eq = pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"] = pd.to_datetime(eq.entry)
g = eq[(eq.vix_gate == True) | (eq.name_gate == True)].drop_duplicates(["symbol", "entry"]).copy()
g["exit"] = g.entry + pd.to_timedelta(g.days_held, unit="D")
g = g.sort_values("entry").reset_index(drop=True)


def run(n_consec=None, pause_days=0, rank_by=None):
    """n_consec: breaker trigger (None=off). rank_by: column to pick best-2/day."""
    open_pos, closed = [], []
    consec, pause_until = 0, pd.Timestamp("1900-01-01")
    name_cd = {}                      # symbol -> cooldown-until (21d name law)
    days = pd.date_range(g.entry.min(), g.exit.max(), freq="D")
    by_day = {d: t for d, t in g.groupby("entry")}
    skipped = {"name_cd": 0, "dedupe": 0, "breaker": 0}
    for day in days:
        # exits first (breaker state updates on exit)
        for p in [p for p in open_pos if p["exit"] <= day]:
            open_pos.remove(p); closed.append(p)
            if p["pnl"] <= 0:
                consec += 1
                name_cd[p["symbol"]] = p["exit"] + pd.Timedelta(days=21)
                if n_consec and consec >= n_consec:
                    pause_until = max(pause_until, day + pd.Timedelta(days=pause_days))
            else:
                consec = 0
        if day not in by_day:
            continue
        cands = by_day[day]
        if rank_by is not None:
            cands = cands.sort_values(rank_by, ascending=False)
        held = {p["symbol"] for p in open_pos}
        taken_today = 0
        for _, r in cands.iterrows():
            if r.symbol in held:
                skipped["dedupe"] += 1; continue
            if taken_today >= 2:
                skipped["dedupe"] += 1; continue
            if r.symbol in name_cd and day < name_cd[r.symbol]:
                skipped["name_cd"] += 1; continue
            if day < pause_until:
                skipped["breaker"] += 1; continue
            open_pos.append(dict(symbol=r.symbol, exit=r.exit, pnl=r.pnl))
            held.add(r.symbol); taken_today += 1
    closed += open_pos
    c = pd.DataFrame(closed).sort_values("exit")
    curve = c.set_index("exit").pnl.cumsum()
    peak = curve.cummax(); dd = (peak - curve).max()
    tot = c.pnl.sum()
    return dict(n=len(c), total=tot, per=tot / len(c), win=100 * (c.pnl > 0).mean(),
                maxdd=dd, ratio=tot / dd if dd else np.inf, skipped=skipped)


print(f"{'config':<38}{'n':>5}{'total':>10}{'$/tr':>7}{'win%':>6}{'maxDD$':>9}{'tot/DD':>7}{'skips(breaker)':>15}")
base = run()
rows = [("BASELINE (dedupe + 21d name-cooldown)", base)]
for n in (2, 3):
    for k in (5, 10, 21):
        rows.append((f"breaker: {n} consec losses -> pause {k}d", run(n_consec=n, pause_days=k)))
rows.append(("rank best-2/day by VRP (no breaker)", run(rank_by="vrp")))
rows.append(("rank best-2/day by iv_rank (no breaker)", run(rank_by="iv_rank")))
for lbl, r in rows:
    print(f"{lbl:<38}{r['n']:>5}{r['total']:>10,.0f}{r['per']:>7.0f}{r['win']:>6.1f}"
          f"{r['maxdd']:>9,.0f}{r['ratio']:>7.2f}{r['skipped']['breaker']:>15}")
