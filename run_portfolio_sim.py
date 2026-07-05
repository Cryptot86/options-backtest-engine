"""Portfolio simulation: TJ allocation model, $50K start, 2019-07 -> 2025-06.
VIX bands: <25 ->35% selling | 25-35 ->40% | 35-50+ ->60%; buying 15% flat.
Capacity enforced by margin estimates; compounding; trades skipped when full.
"""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np
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

def sell_alloc(v):   # user's bands
    return 0.35 if v < 25 else 0.40 if v < 35 else 0.60

con = db._conn()
trades = []
# 1) equities: gated bb_2sd + five_day_low, top 15 (1 contract each)
runs = db.list_runs(); eq = runs[(runs.phase=="phase1_realiv")&(runs.run_id>=32)].run_id.tolist()
te = pd.read_sql(f'SELECT symbol,entry_date,exit_date,strike,pnl FROM trades '
    f'WHERE run_id IN ({",".join(map(str,eq))}) AND signal_type IN ("bb_2sd","five_day_low")', con)
te = te[te.symbol.isin(TOP15)]
for c in ("entry_date","exit_date"): te[c]=pd.to_datetime(te[c])
te = te[te.entry_date.map(lambda d: bool(gate.get(d,False)))]
for _,r in te.iterrows():
    trades.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl,
                       margin=0.20*r.strike*100, book="sell", tag=f"EQ {r.symbol}"))
# 2) MES puts (ES run 66 / 10)
t = pd.read_sql("SELECT entry_date,exit_date,strike,pnl FROM trades WHERE run_id=66 "
                "AND signal_type IN ('bb_2sd','five_day_low')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t.iterrows():
    trades.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl/10.0,
                       margin=1300.0, book="sell", tag="MES put"))
# 3) CL + NG calls (D+1 runs, 1 full contract)
for rid, mg, tag in ((28,3500.0,"CL call"),(27,2800.0,"NG call")):
    t = pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} "
                    f"AND signal_type='bb_2sd_call'", con)
    for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
    for _,r in t.iterrows():
        trades.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl, margin=mg,
                           book="sell", tag=tag))
# 4) long calls micro (run 33 ES+GC / 10): margin = debit
t = pd.read_sql("SELECT entry_date,exit_date,entry_credit,pnl FROM trades WHERE run_id=33 "
                "AND symbol IN ('ES','GC')", con)
for c in ("entry_date","exit_date"): t[c]=pd.to_datetime(t[c])
for _,r in t.iterrows():
    trades.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl/10.0,
                       margin=abs(r.entry_credit)/10.0, book="buy", tag="micro long call"))

T = pd.DataFrame([t for t in trades if t["d"]>=START]).sort_values("d").reset_index(drop=True)
print(f"candidate trades: {len(T)} ({(T.book=='sell').sum()} sell / {(T.book=='buy').sum()} buy)")

equity, open_pos, taken, skipped = EQ0, [], 0, 0
curve = []
for day in pd.date_range(START, "2025-06-30", freq="D"):
    for p in [p for p in open_pos if p["x"]<=day]:          # close positions
        equity += p["pnl"]; open_pos.remove(p)
    v = float(vix.asof(day)) if not np.isnan(vix.asof(day)) else 20.0
    capS, capB = sell_alloc(v)*equity, 0.15*equity
    usedS = sum(p["margin"] for p in open_pos if p["book"]=="sell")
    usedB = sum(p["margin"] for p in open_pos if p["book"]=="buy")
    for _,r in T[T.d==day].iterrows():
        cap, used = (capS, usedS) if r.book=="sell" else (capB, usedB)
        if used + r.margin <= cap:
            open_pos.append(dict(r)); taken += 1
            if r.book=="sell": usedS += r.margin
            else: usedB += r.margin
        else: skipped += 1
    curve.append((day, equity + 0))
cv = pd.Series(dict(curve)).sort_index()
for p in open_pos: equity += p["pnl"]
yrs = (cv.index[-1]-cv.index[0]).days/365.25
dd = (cv-cv.cummax()).min()
print(f"\ntaken {taken} | skipped (capacity) {skipped}")
print(f"FINAL EQUITY: ${equity:,.0f}  from $50,000  ({(equity/EQ0-1)*100:+.0f}%)")
print(f"CAGR: {((equity/EQ0)**(1/yrs)-1)*100:.1f}%  | max drawdown: ${dd:,.0f} "
      f"({100*dd/cv.cummax()[ (cv-cv.cummax()).idxmin() ]:.0f}%)")
print("\nyear-end equity:")
print(cv.resample("YE").last().round(0).to_string())
print("PORTFOLIO SIM DONE")
