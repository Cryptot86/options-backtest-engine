"""Calm-band sweep on final-config v2: sell cap when VIX<25 at 25/35/45%."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np, yfinance as yf
from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.signals.indicators import realized_vol
EQ0, END = 50_000.0, "2026-06-30"; START=pd.Timestamp("2019-07-01")
vix = get_prices("^VIX","2017-01-01",END)["close"]
spy = get_prices("SPY","2017-01-01",END)["close"]
vrank = vix.rolling(252).apply(lambda w:(w.iloc[-1]>=w).mean())
gate = (vrank>=0.5)&((vix-realized_vol(spy,20).reindex(vix.index)*100)>0)&(vix.diff(5)<=0)
con=db._conn(); runs=db.list_runs()
eq = runs[runs.phase=="phase1_realiv"].copy(); eq["uni"]=eq.universe.astype(str)
names = sorted({u.strip("[]'\" ") for u in eq.uni if len(u.strip("[]'\" "))<=5 and u.strip("[]'\" ").isalpha()})
ids = sorted({int(eq[eq.uni.str.contains(n)].iloc[0].run_id) for n in names})
te = pd.read_sql(f'SELECT symbol,entry_date,exit_date,strike,entry_iv,pnl FROM trades WHERE run_id IN ({",".join(map(str,ids))}) '
                 f'AND signal_type IN ("bb_2sd","five_day_low")', con)
for c in ("entry_date","exit_date"): te[c]=pd.to_datetime(te[c])
te=te.drop_duplicates(subset=["symbol","entry_date"]); te=te[te.entry_date>=START]
FACT=[1,2,3,4,10,15,20,40]
rows=[]
for s in names:
    try:
        p=get_prices(s,"2019-01-01",END)["close"]
        edd=pd.to_datetime(yf.Ticker(s).get_earnings_dates(limit=60).index).tz_localize(None).normalize()
    except Exception: continue
    rv=realized_vol(p,20); rank=rv.rolling(252).apply(lambda z:(z.iloc[-1]>=z).mean())
    d=te[te.symbol==s].copy()
    if not len(d): continue
    se=p.asof(d.entry_date).values
    d["m"]=[min(FACT,key=lambda f: abs((k/f)/sp-0.92)) if sp==sp else 1 for k,sp in zip(d.strike,se)]
    d["pnl_adj"]=d.pnl/d.m; d["margin"]=0.2*(d.strike/d.m)*100
    d["rv"]=rv.asof(d.entry_date).values; d["nrank"]=rank.asof(d.entry_date).values
    d["nslope"]=rv.diff(5).asof(d.entry_date).values
    d["earn"]=[bool(((edd>a)&(edd<=b)).any()) for a,b in zip(d.entry_date,d.exit_date)]
    rows.append(d)
te=pd.concat(rows); te["mkt"]=te.entry_date.map(lambda d: bool(gate.get(d,False)))
tr=[]
for _,r in te[te.mkt & ~te.earn].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl_adj,margin=r.margin,book="sell"))
for _,r in te[(~te.mkt)&(te.nrank>=0.5)&(te.nslope<=0)&(te.entry_iv>te.rv)&(~te.earn)].iterrows():
    tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl_adj,margin=r.margin,book="sell"))
def latest(ph,u):
    m=runs[(runs.phase==ph)&(runs.universe==u)]
    return int(m.iloc[0].run_id) if len(m) else None
rid=latest("futures_glbx_lag1","ES")
t=pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} AND signal_type IN ('bb_2sd','five_day_low')",con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t[t.entry_date>=START].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl/10,margin=1300,book="sell"))
for root,mg in (("NG",2800),("CL",3500)):
    rid=latest("futures_glbx_calls_lag1",root)
    t=pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} AND signal_type='bb_2sd_call'",con)
    for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
    for _,r in t[t.entry_date>=START].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl,margin=mg,book="sell"))
T=pd.DataFrame(tr).sort_values("d")
days=pd.date_range(START,END,freq="D"); vd=vix.reindex(days,method="ffill").fillna(20.0)
byd={d:g for d,g in T.groupby("d")}
def sim(calm):
    eq,op=EQ0,[]; curve=np.empty(len(days)); taken=skipped=0
    for i,day in enumerate(days):
        for p_ in [p_ for p_ in op if p_["x"]<=day]: eq+=p_["pnl"]; op.remove(p_)
        v=vd.iloc[i]; capS=(calm if v<25 else 0.50 if v<35 else 0.60)*eq
        uS=sum(p_["margin"] for p_ in op)
        idle=max(0.0,eq-uS-0.10*eq); eq+=idle*0.04/365
        if day in byd:
            for _,r in byd[day].iterrows():
                if uS+r.margin<=capS: op.append(dict(r)); uS+=r.margin; taken+=1
                else: skipped+=1
        curve[i]=eq
    for p_ in op: eq+=p_["pnl"]
    cv=pd.Series(curve,index=days); dd=((cv-cv.cummax())/cv.cummax()).min()
    yrs=(days[-1]-days[0]).days/365.25; cagr=(eq/EQ0)**(1/yrs)-1
    return eq,cagr,dd,taken,skipped
for calm in (0.25,0.35,0.45):
    e,c,d,t2,s2=sim(calm)
    print(f"calm band {int(calm*100)}%: final ${e:,.0f} | CAGR {c*100:.1f}% | maxDD {d*100:.1f}% | MAR {c/abs(d):.2f} | taken {t2} skipped {s2}", flush=True)
print("BAND SWEEP DONE")
