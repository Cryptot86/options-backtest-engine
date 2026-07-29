#!/usr/bin/env python
"""Portfolio allocation sweep — $50K from 2015, micro sell-book, VIX-band budget.

Question: is 'VIX<25 -> deploy 25% of equity to selling' optimal, or does another
band combo grow the account more per unit of drawdown? Sweeps the calm band.
VIX proxy = SPY 30d IVX*100 (our IV series, offline, back to 2013). Capacity
enforced (skip when the VIX-band margin budget is full = the correlation filter).
"""
from __future__ import annotations
import os, itertools, sqlite3, numpy as np, pandas as pd

EQ0, START, END = 50_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
IVDIR = "data_cache/iv_series/stocks"

# ---- VIX proxy from SPY IVX (offline) ----
spy = pd.read_parquet(os.path.join(IVDIR, "SPY.parquet"))
vix = (spy["iv30"] * 100).rename("vix"); vix.index = pd.to_datetime(vix.index)

# ---- assemble the micro sell-book ----
trades = []
# equities: VIX-gated stock puts (IVol book), 1 contract, RegT-ish margin
eq = pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"] = pd.to_datetime(eq.entry)
eq = eq[eq.vix_gate == True]
for r in eq.itertuples():
    ex = r.entry + pd.Timedelta(days=int(r.days_held))
    trades.append(dict(d=r.entry, x=ex, pnl=r.pnl, margin=max(0.18*r.strike*100, 500), tag="EQ"))
# futures micros from the DB (pnl/10 = micro), rough SPAN margins
con = sqlite3.connect("db/results.sqlite")
FUT = [(66, "MES", ["bb_2sd","five_day_low"], 1300), (28, "MCL", ["bb_2sd_call"], 350),
       (27, "MNG", ["bb_2sd_call"], 280), (30, "MGC", ["bb_2sd"], 220)]
for rid, tag, sigs, mg in FUT:
    root = tag[1:]
    q = f"SELECT entry_date,pnl,days_held FROM trades WHERE run_id={rid} AND signal_type IN ({','.join(repr(s) for s in sigs)})"
    t = pd.read_sql(q, con)
    if t.empty: continue
    t["entry_date"] = pd.to_datetime(t.entry_date)
    for r in t.itertuples():
        trades.append(dict(d=r.entry_date, x=r.entry_date+pd.Timedelta(days=int(r.days_held)),
                           pnl=r.pnl/10.0, margin=mg, tag=tag))
con.close()
T = pd.DataFrame([x for x in trades if x["d"] >= START]).sort_values("d").reset_index(drop=True)
print(f"sell-book trades {START.date()}..: {len(T)}  ({T.tag.value_counts().to_dict()})\n")

def simulate(calm, mid, high):
    def band(v): return (calm if v < 25 else mid if v < 35 else high)
    equity, openp, taken, skipped = EQ0, [], 0, 0
    curve = {}
    days = pd.date_range(START, END, freq="D")
    Tby = {d: g for d, g in T.groupby("d")}
    for day in days:
        for p in [p for p in openp if p["x"] <= day]:
            equity += p["pnl"]; openp.remove(p)
        v = vix.asof(day); v = 20.0 if pd.isna(v) else v
        capS = band(v) * equity
        usedS = sum(p["margin"] for p in openp)
        if day in Tby:
            for _, r in Tby[day].iterrows():
                if usedS + r.margin <= capS:
                    openp.append(dict(r)); usedS += r.margin; taken += 1
                else: skipped += 1
        curve[day] = equity
    for p in openp: equity += p["pnl"]
    cv = pd.Series(curve)
    yrs = (cv.index[-1]-cv.index[0]).days/365.25
    peak = cv.cummax(); ddser = (peak-cv)/peak
    cagr = (equity/EQ0)**(1/yrs)-1
    return dict(final=equity, cagr=cagr, mddp=ddser.max(), mar=cagr/ddser.max() if ddser.max() else 0,
                taken=taken, skipped=skipped, curve=cv)

print(f"{'bands (calm/mid/high)':<24}{'final$':>10}{'CAGR':>7}{'maxDD%':>8}{'MAR':>6}{'taken':>7}{'skip':>6}")
best = None
combos = [(0.15,0.40,0.60),(0.20,0.45,0.60),(0.25,0.50,0.60),(0.30,0.55,0.60),
          (0.35,0.55,0.60),(0.50,0.60,0.70),(0.25,0.25,0.25),(1.0,1.0,1.0)]
res = {}
for c,m,h in combos:
    r = simulate(c,m,h); res[(c,m,h)] = r
    lbl = "flat "+f"{int(c*100)}%" if c==m==h else f"{int(c*100)}/{int(m*100)}/{int(h*100)}"
    print(f"{lbl:<24}${r['final']:>9,.0f}{100*r['cagr']:>6.1f}%{100*r['mddp']:>7.1f}%{r['mar']:>6.2f}{r['taken']:>7}{r['skipped']:>6}")
    if best is None or r['mar']>res[best]['mar']: best=(c,m,h)
print(f"\nBEST by MAR: {best} -> final ${res[best]['final']:,.0f}, MAR {res[best]['mar']:.2f}")
print("\nyear-end equity for the 25/50/60 (current law) config:")
print(res[(0.25,0.50,0.60)]['curve'].resample("YE").last().round(0).to_string())
