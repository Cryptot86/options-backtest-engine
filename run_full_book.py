#!/usr/bin/env python
"""FULL BOOK sim — $50K from 2015, ALL sleeves + SIZE-STEPS + T-bills + optimal alloc.
Sleeves: gated+name-gate equity puts, MES puts, MCL/MNG calls, MGC puts (SELL);
straddles + ES/GC long-calls (BUY 15%); T-bill 2% on idle. Size-steps scale
contracts with equity. Alloc: loose 50% sell band + dedupe + cluster caps.
"""
from __future__ import annotations
import os, sqlite3, numpy as np, pandas as pd
EQ0, START, END = 50_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
IVDIR="data_cache/iv_series/stocks"
spy=pd.read_parquet(os.path.join(IVDIR,"SPY.parquet")); vix=(spy["iv30"]*100); vix.index=pd.to_datetime(vix.index)
RF=0.02/252  # T-bill daily on idle (rate-honest ~2% avg)
# line: cluster, tail_anchor, base_margin, cap
LINE={"EQ":("EQIDX",4520,1200,1),"MES":("EQIDX",1569,1300,2),"MCL":("ENERGY",290,350,5),
      "MNG":("ENERGY",200,280,5),"MGC":("METALS",823,220,2)}
CAP={"ENERGY":0.05,"METALS":0.05,"EQIDX":0.07}   # + total 12%
def qty(tag,equity):
    cl,anc,mg,cap=LINE[tag]; return int(np.clip(np.floor(0.02*equity/anc),1,cap))

trades=[]
eq=pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"]=pd.to_datetime(eq.entry)
eq=eq[(eq.vix_gate==True)|(eq.name_gate==True)].drop_duplicates(["symbol","entry"])
for r in eq.itertuples():
    trades.append(dict(d=r.entry,x=r.entry+pd.Timedelta(days=int(r.days_held)),pnl1=r.pnl,
        tag="EQ",cluster="EQIDX",margin=1200,name=f"EQ:{r.symbol}",book="sell"))
con=sqlite3.connect("db/results.sqlite")
for rid,tag,sigs in [(66,"MES",["bb_2sd","five_day_low"]),(28,"MCL",["bb_2sd_call"]),
                     (27,"MNG",["bb_2sd_call"]),(30,"MGC",["bb_2sd"])]:
    cl,anc,mg,cap=LINE[tag]
    t=pd.read_sql(f"SELECT entry_date,pnl,days_held FROM trades WHERE run_id={rid} AND signal_type IN ({','.join(repr(s) for s in sigs)})",con)
    if t.empty: continue
    t["entry_date"]=pd.to_datetime(t.entry_date)
    for r in t.itertuples():
        trades.append(dict(d=r.entry_date,x=r.entry_date+pd.Timedelta(days=int(r.days_held)),
            pnl1=r.pnl/10.0,tag=tag,cluster=cl,margin=mg,name=tag,book="sell"))
# BUY book: straddles (cheap) + ES/GC long calls, micro, 1-lot (buy 15%)
strad_runs=[71,84,96,90,91,100,101,102,103,105]
for rid in strad_runs:
    t=pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} AND signal_type='straddle_cheap'",con)
    if t.empty: continue
    fut = rid in (71,84,96)
    for r in t.itertuples():
        e=pd.to_datetime(r.entry_date)
        trades.append(dict(d=e,x=e+pd.Timedelta(days=21),pnl1=(r.pnl/10.0 if fut else r.pnl),
            tag="STRAD",cluster="LONGVOL",margin=1500,name=f"STRAD{rid}",book="buy"))
lc=pd.read_sql("SELECT entry_date,pnl FROM trades WHERE run_id=33 AND symbol IN ('ES','GC')",con)
for r in lc.itertuples():
    e=pd.to_datetime(r.entry_date)
    trades.append(dict(d=e,x=e+pd.Timedelta(days=30),pnl1=r.pnl/10.0,tag="LCALL",cluster="LONGCALL",margin=500,name="LCALL",book="buy"))
con.close()
T=pd.DataFrame([x for x in trades if x["d"]>=START]).sort_values("d").reset_index(drop=True)
print(f"full book trades {START.date()}..: {len(T)}  ({T.tag.value_counts().to_dict()})\n")

def run(sell_band=0.50, buy_band=0.15, sizesteps=True):
    equity,openp,taken,skip=EQ0,[],0,0; curve={}; last=EQ0
    Tby={d:g for d,g in T.groupby("d")}
    for day in pd.date_range(START,END,freq="D"):
        for p in [p for p in openp if p["x"]<=day]:
            equity+=p["realpnl"]; openp.remove(p)
        deployed=sum(p["m"] for p in openp)
        equity+=max(equity-deployed,0)*RF   # T-bill on idle
        capS=sell_band*equity; capB=buy_band*equity
        usedS=sum(p["m"] for p in openp if p["book"]=="sell"); usedB=sum(p["m"] for p in openp if p["book"]=="buy")
        names={p["name"] for p in openp}; eqday=0
        if day in Tby:
            for _,r in Tby[day].iterrows():
                q = qty(r.tag,equity) if (sizesteps and r.tag in LINE) else 1
                mgn=r.margin*q; ok=True
                if r["name"] in names: ok=False
                if r.tag=="EQ" and eqday>=2: ok=False
                cap,used=(capS,usedS) if r.book=="sell" else (capB,usedB)
                if used+mgn>cap: ok=False
                if r.cluster in CAP:
                    ct=sum(p["tail"] for p in openp if p["cluster"]==r.cluster)
                    tanc=LINE.get(r.tag,("",mgn))[1] if r.tag in LINE else mgn
                    if ct+tanc*q>CAP[r.cluster]*equity: ok=False
                # total-cluster cap 12%
                tot=sum(p["tail"] for p in openp)
                if r.tag in LINE and tot+LINE[r.tag][1]*q>0.12*equity: ok=False
                if ok:
                    tanc=LINE[r.tag][1]*q if r.tag in LINE else 0
                    openp.append(dict(name=r["name"],x=r.x,realpnl=r.pnl1*q,m=mgn,tail=tanc,
                                      book=r.book,cluster=r.cluster)); taken+=1
                    if r.book=="sell": usedS+=mgn
                    else: usedB+=mgn
                    names.add(r["name"])
                    if r.tag=="EQ": eqday+=1
                else: skip+=1
        curve[day]=equity
    for p in openp: equity+=p["realpnl"]
    cv=pd.Series(curve); yrs=(cv.index[-1]-cv.index[0]).days/365.25
    dd=((cv.cummax()-cv)/cv.cummax()).max()
    return dict(final=equity,cagr=(equity/EQ0)**(1/yrs)-1,mddp=dd,mar=((equity/EQ0)**(1/yrs)-1)/dd if dd else 0,taken=taken,skip=skip,curve=cv)

for tag,ss in [("1-contract (no size-steps)",False),("SIZE-STEPS (contracts scale w/ equity)",True)]:
    r=run(sizesteps=ss)
    print(f"{tag}")
    print(f"  $50,000 -> ${r['final']:,.0f}  ({100*(r['final']/EQ0-1):+.0f}%)  CAGR {100*r['cagr']:.1f}%  maxDD {100*r['mddp']:.1f}%  MAR {r['mar']:.2f}  (taken {r['taken']}, skip {r['skip']})")
print("\nyear-end equity (full book, size-steps):")
print(run(sizesteps=True)['curve'].resample("YE").last().round(0).to_string())
