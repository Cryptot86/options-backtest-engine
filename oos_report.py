"""OOS report: trades entered 2025-07-01..2026-06-30 under frozen rules."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np
from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.signals.indicators import realized_vol
OOS = pd.Timestamp("2025-07-01")
TOP15 = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","AVGO","JPM","COST","LLY","UNH","HD"]
vix = get_prices("^VIX","2017-01-01","2026-06-30")["close"]
spy = get_prices("SPY","2017-01-01","2026-06-30")["close"]
rank = vix.rolling(252).apply(lambda w:(w.iloc[-1]>=w).mean())
gate = (rank>=0.5)&((vix-realized_vol(spy,20).reindex(vix.index)*100)>0)&(vix.diff(5)<=0)
con = db._conn(); runs = db.list_runs()
tr=[]
def latest(phase, uni):
    m = runs[(runs.phase==phase)&(runs.universe==uni)]
    return int(m.iloc[0].run_id) if len(m) else None
eq_ids=[]
for s in TOP15:
    r = latest("phase1_realiv", s)
    if r: eq_ids.append(r)
te = pd.read_sql(f'SELECT symbol,entry_date,exit_date,strike,pnl FROM trades '
    f'WHERE run_id IN ({",".join(map(str,eq_ids))}) AND signal_type IN ("bb_2sd","five_day_low")', con)
for c in ("entry_date","exit_date"): te[c]=pd.to_datetime(te[c])
te = te[(te.entry_date>=OOS) & te.entry_date.map(lambda d: bool(gate.get(d,False)))]
for _,r in te.iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl,tag=f"EQ",margin=0.2*r.strike*100,book="sell"))
rid = latest("futures_glbx_lag1","ES")
t = pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} AND signal_type IN ('bb_2sd','five_day_low')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t[t.entry_date>=OOS].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl/10.0,tag="MES",margin=1300,book="sell"))
for root,mg in (("NG",2800),("CL",3500)):
    rid = latest("futures_glbx_calls_lag1",root)
    t = pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} AND signal_type='bb_2sd_call'", con)
    for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
    for _,r in t[t.entry_date>=OOS].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl,tag=f"{root}c",margin=mg,book="sell"))
rid = latest("long_call_cross","multi")
t = pd.read_sql(f"SELECT entry_date,exit_date,entry_credit,pnl FROM trades WHERE run_id={rid} AND symbol IN ('ES','GC')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t[t.entry_date>=OOS].iterrows(): tr.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl/10.0,tag="uLC",margin=abs(r.entry_credit)/10.0,book="buy"))
T = pd.DataFrame(tr).sort_values("d")
print(f"OOS trades (2025-07 .. 2026-06): {len(T)}")
if len(T):
    T["exit_month"]=T.x.dt.strftime("%Y-%m")
    m = T.groupby("exit_month")["pnl"].sum().round(0)
    print("\nMONTH-BY-MONTH (booked at exit):"); print(m.to_string())
    print(f"\nTOTAL OOS: ${T.pnl.sum():,.0f}  | trades: {len(T)} | win% {100*(T.pnl>0).mean():.0f}")
    print("by line:"); print(T.groupby("tag")["pnl"].agg(["size","sum"]).round(0).to_string())
print("OOS REPORT DONE")
