#!/usr/bin/env python
"""DEFINITIVE portfolio sweep — $50K from 2015, full micro book, ALL controls:
  VIX-margin band (swept) + DEDUPE (equities: one/name, max 2 new/day) +
  CLUSTER TAIL CAPS (energy 5%, metals 5%; equity-index uses dedupe not a cap,
  per validated finding). Finds the optimal allocation rule.
"""
from __future__ import annotations
import os, sqlite3, numpy as np, pandas as pd

EQ0, START, END = 50_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
IVDIR = "data_cache/iv_series/stocks"
spy = pd.read_parquet(os.path.join(IVDIR, "SPY.parquet"))
vix = (spy["iv30"] * 100).rename("vix"); vix.index = pd.to_datetime(vix.index)

# cluster + tail-anchor (worst-case $/contract) + margin per line
LINE = {  # tag: (cluster, tail_anchor, margin)
  "MES": ("EQIDX", 1569, 1300), "MCL": ("ENERGY", 290, 350),
  "MNG": ("ENERGY", 200, 280), "MGC": ("METALS", 823, 220)}
CAP = {"ENERGY": 0.05, "METALS": 0.05}   # equity-index -> dedupe, no hard cap

trades = []
eq = pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"]=pd.to_datetime(eq.entry)
eq = eq[eq.vix_gate==True]
for r in eq.itertuples():
    trades.append(dict(d=r.entry, x=r.entry+pd.Timedelta(days=int(r.days_held)), pnl=r.pnl,
                       margin=max(0.18*r.strike*100,500), cluster="EQIDX", anchor=3500,
                       name=f"EQ:{r.symbol}", tag="EQ"))
con=sqlite3.connect("db/results.sqlite")
for rid,tag,sigs in [(66,"MES",["bb_2sd","five_day_low"]),(28,"MCL",["bb_2sd_call"]),
                     (27,"MNG",["bb_2sd_call"]),(30,"MGC",["bb_2sd"])]:
    cl,anc,mg=LINE[tag]
    t=pd.read_sql(f"SELECT entry_date,pnl,days_held FROM trades WHERE run_id={rid} AND signal_type IN ({','.join(repr(s) for s in sigs)})",con)
    if t.empty: continue
    t["entry_date"]=pd.to_datetime(t.entry_date)
    for r in t.itertuples():
        trades.append(dict(d=r.entry_date,x=r.entry_date+pd.Timedelta(days=int(r.days_held)),
                           pnl=r.pnl/10.0,margin=mg,cluster=cl,anchor=anc,name=tag,tag=tag))
con.close()
T=pd.DataFrame([x for x in trades if x["d"]>=START]).sort_values("d").reset_index(drop=True)
print(f"trades {START.date()}..: {len(T)} ({T.tag.value_counts().to_dict()})\n")

def simulate(calm,mid,high):
    def band(v): return calm if v<25 else mid if v<35 else high
    equity,openp,taken,skip=EQ0,[],0,0; curve={}
    Tby={d:g for d,g in T.groupby("d")}
    for day in pd.date_range(START,END,freq="D"):
        for p in [p for p in openp if p["x"]<=day]:
            equity+=p["pnl"]; openp.remove(p)
        v=vix.asof(day); v=20.0 if pd.isna(v) else v
        capS=band(v)*equity; usedS=sum(p["margin"] for p in openp)
        openames={p["name"] for p in openp}
        eq_today=0
        if day in Tby:
            for _,r in Tby[day].iterrows():
                ok=True
                # dedupe: one open per name; equities max 2 new/day
                if r["name"] in openames: ok=False
                if r.tag=="EQ" and eq_today>=2: ok=False
                # margin band
                if usedS+r.margin>capS: ok=False
                # cluster tail cap (energy/metals)
                if r.cluster in CAP:
                    ctail=sum(p["anchor"] for p in openp if p["cluster"]==r.cluster)
                    if ctail+r.anchor>CAP[r.cluster]*equity: ok=False
                if ok:
                    openp.append(dict(r)); usedS+=r.margin; taken+=1
                    openames.add(r["name"])
                    if r.tag=="EQ": eq_today+=1
                else: skip+=1
        curve[day]=equity
    for p in openp: equity+=p["pnl"]
    cv=pd.Series(curve); yrs=(cv.index[-1]-cv.index[0]).days/365.25
    dd=((cv.cummax()-cv)/cv.cummax()).max(); cagr=(equity/EQ0)**(1/yrs)-1
    return dict(final=equity,cagr=cagr,mddp=dd,mar=cagr/dd if dd else 0,taken=taken,skip=skip,curve=cv)

print(f"{'bands calm/mid/high':<22}{'final$':>10}{'CAGR':>7}{'maxDD%':>8}{'MAR':>6}{'taken':>7}{'skip':>6}")
res={}
for c,m,h in [(0.15,0.40,0.60),(0.25,0.50,0.60),(0.35,0.55,0.60),(0.50,0.60,0.70),
              (0.60,0.70,0.80),(1.0,1.0,1.0)]:
    r=simulate(c,m,h); res[(c,m,h)]=r
    lbl="flat 100%" if c==m==h==1.0 else f"{int(c*100)}/{int(m*100)}/{int(h*100)}"
    print(f"{lbl:<22}${r['final']:>9,.0f}{100*r['cagr']:>6.1f}%{100*r['mddp']:>7.1f}%{r['mar']:>6.2f}{r['taken']:>7}{r['skip']:>6}")
best=max(res,key=lambda k:res[k]['mar'])
print(f"\nBEST by MAR: {best} -> final ${res[best]['final']:,.0f}, CAGR {100*res[best]['cagr']:.1f}%, maxDD {100*res[best]['mddp']:.1f}%, MAR {res[best]['mar']:.2f}")
print("year-end equity (best config):")
print(res[best]['curve'].resample("YE").last().round(0).to_string())
