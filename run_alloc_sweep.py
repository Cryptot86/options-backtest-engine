"""Allocation-band sweep, scored on Toyota metrics (MAR = CAGR/|maxDD|)."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np, itertools
from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.signals.indicators import realized_vol

START, EQ0 = pd.Timestamp("2019-07-01"), 50_000.0
TOP15 = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","AVGO",
         "JPM","COST","LLY","UNH","HD"]
vix = get_prices("^VIX","2017-01-01","2025-06-30")["close"]
spy = get_prices("SPY","2017-01-01","2025-06-30")["close"]
rank = vix.rolling(252).apply(lambda w:(w.iloc[-1]>=w).mean())
gate = (rank>=0.5)&((vix-realized_vol(spy,20).reindex(vix.index)*100)>0)&(vix.diff(5)<=0)

con = db._conn()
trades = []
runs = db.list_runs(); eq = runs[(runs.phase=="phase1_realiv")&(runs.run_id>=32)].run_id.tolist()
te = pd.read_sql(f'SELECT symbol,entry_date,exit_date,strike,pnl FROM trades '
    f'WHERE run_id IN ({",".join(map(str,eq))}) AND signal_type IN ("bb_2sd","five_day_low")', con)
te = te[te.symbol.isin(TOP15)]
for c in ("entry_date","exit_date"): te[c]=pd.to_datetime(te[c])
te = te[te.entry_date.map(lambda d: bool(gate.get(d,False)))]
for _,r in te.iterrows():
    trades.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl,margin=0.20*r.strike*100,book="sell"))
t = pd.read_sql("SELECT entry_date,exit_date,pnl FROM trades WHERE run_id=66 "
                "AND signal_type IN ('bb_2sd','five_day_low')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t.iterrows():
    trades.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl/10.0,margin=1300.0,book="sell"))
for rid,mg in ((28,3500.0),(27,2800.0)):
    t = pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} "
                    f"AND signal_type='bb_2sd_call'", con)
    for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
    for _,r in t.iterrows():
        trades.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl,margin=mg,book="sell"))
t = pd.read_sql("SELECT entry_date,exit_date,entry_credit,pnl FROM trades WHERE run_id=33 "
                "AND symbol IN ('ES','GC')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t.iterrows():
    trades.append(dict(d=r.entry_date,x=r.exit_date,pnl=r.pnl/10.0,
                       margin=abs(r.entry_credit)/10.0,book="buy"))
T = pd.DataFrame([x for x in trades if x["d"]>=START]).sort_values("d").reset_index(drop=True)
days = pd.date_range(START,"2025-06-30",freq="D")
vix_d = vix.reindex(days, method="ffill").fillna(20.0)
byday = {d: g for d, g in T.groupby("d")}

def sim(base, mid, high, buyA):
    equity, open_pos = EQ0, []
    curve = np.empty(len(days))
    for i, day in enumerate(days):
        for p in [p for p in open_pos if p["x"]<=day]:
            equity += p["pnl"]; open_pos.remove(p)
        v = vix_d.iloc[i]
        capS = (base if v<25 else mid if v<35 else high)*equity
        capB = buyA*equity
        usedS = sum(p["margin"] for p in open_pos if p["book"]=="sell")
        usedB = sum(p["margin"] for p in open_pos if p["book"]=="buy")
        if day in byday:
            for _,r in byday[day].iterrows():
                cap,used = (capS,usedS) if r.book=="sell" else (capB,usedB)
                if used + r.margin <= cap:
                    open_pos.append(dict(r))
                    if r.book=="sell": usedS += r.margin
                    else: usedB += r.margin
        curve[i] = equity
    for p in open_pos: equity += p["pnl"]
    cv = pd.Series(curve, index=days)
    yrs = 6.0
    cagr = (equity/EQ0)**(1/yrs)-1
    ddpct = ((cv-cv.cummax())/cv.cummax()).min()
    yearly = cv.resample("YE").last().pct_change().dropna()
    worst_yr = yearly.min()
    return equity, cagr*100, ddpct*100, (cagr/abs(ddpct)) if ddpct<0 else 99, worst_yr*100

print(f"{'base/mid/high/buy':>20} {'final':>9} {'CAGR':>6} {'maxDD':>7} {'MAR':>5} {'worst yr':>8}")
res=[]
for base,mid,high,buyA in itertools.product((0.25,0.35,0.50),(0.40,0.50),(0.60,0.70),(0.05,0.10,0.15)):
    if not (base<=mid<=high): continue
    e,c,d,m,w = sim(base,mid,high,buyA)
    res.append((f"{int(base*100)}/{int(mid*100)}/{int(high*100)}/{int(buyA*100)}",e,c,d,m,w))
# also flat + inverse variants
for lbl,(b,mi,h,bu) in {"FLAT 40/40/40/15":(0.40,0.40,0.40,0.15),
                        "INVERSE 60/40/25/15":(0.60,0.40,0.25,0.15)}.items():
    e,c,d,m,w = sim(b,mi,h,bu); res.append((lbl,e,c,d,m,w))
res.sort(key=lambda r:-r[4])
for lbl,e,c,d,m,w in res[:10]:
    print(f"{lbl:>20} {e:>9,.0f} {c:>5.1f}% {d:>6.1f}% {m:>5.2f} {w:>7.1f}%")
print("\n(user's original = 35/40/60/15)")
print("SWEEP DONE")
