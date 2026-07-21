"""Does fast-40's freed capital recapture its per-trade deficit via recycling?
ES 16d puts, micro-sized, $50K banded sell bucket, capacity enforced.
Book A: flat 50%/21. Book B: 40% if <=5d else 50%/21 (earlier exits -> more capacity)."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
from src.otbt.data.prices import get_prices

cont = gx.get_continuous("ES", "2012-01-01", "2026-06-30")
pp = _prep(cont); idx = pp.index
bb = (pp["close"] <= pp["bb_lower"]) & pp["trend_up"]
fdl = (pp["close"] <= pp["close"].rolling(5).min().shift(1)) & pp["trend_up"]
paths=[]
for d in idx[bb|fdl]:
    pos = idx.searchsorted(d)+1
    if pos>=len(idx): continue
    e = idx[pos]; iv = float(pp.loc[d,"rvol20"]) if pd.notna(pp.loc[d,"rvol20"]) else 0.2
    try:
        S = gx.select_delta_option("ES", e, iv, kind="put", target_delta=0.16)
        if S is None: continue
        p = gx.get_option_path(S.raw_symbol, e, S.expiration).set_index("date")["mid"]
        if e not in p.index or float(p.loc[e])<=0: continue
        paths.append((e,S,p,float(p.loc[e])))
    except Exception: pass
print(f"paths: {len(paths)}", flush=True)
def resolve(mode):
    rows=[]
    for e,S,p,c0 in paths:
        days = pp.loc[e:S.expiration].index; xv=None; xd=days[-1]
        for n,dt in enumerate(days[1:],1):
            if dt in p.index:
                v=float(p.loc[dt]); dte=(S.expiration-dt).days
                fast = (mode=="fast40" and n<=5 and v<=0.6*c0)
                if fast or v<=0.5*c0 or dte<=21: xv=v; xd=dt; break
        if xv is None:
            F=float(pp.loc[xd,"close"]); xv=max(S.strike-F,0.0)
        rows.append(dict(d=e,x=xd,pnl=((c0-xv)*50-25)/10.0))   # MES micro
    return pd.DataFrame(rows)
vix = get_prices("^VIX","2011-01-01","2026-06-30")["close"]
def sim(T):
    days=pd.date_range(T.d.min(),"2026-06-30",freq="D"); vd=vix.reindex(days,method="ffill").fillna(20.0)
    byd={d:g for d,g in T.groupby("d")}
    eq, op, taken, skipped = 50_000.0, [], 0, 0
    for i,day in enumerate(days):
        for p_ in [p_ for p_ in op if p_["x"]<=day]: eq+=p_["pnl"]; op.remove(p_)
        v=vd.iloc[i]; capS=(0.25 if v<25 else 0.50 if v<35 else 0.60)*eq
        uS=len(op)*1300.0
        if day in byd:
            for _,r in byd[day].iterrows():
                if uS+1300.0<=capS: op.append(dict(r)); uS+=1300.0; taken+=1
                else: skipped+=1
    for p_ in op: eq+=p_["pnl"]
    return eq, taken, skipped
for mode,label in (("flat50","flat 50%/21"),("fast40","fast-40 + recycle")):
    T=resolve(mode); e,t,s = sim(T)
    print(f"{label:>20}: final ${e:,.0f} | taken {t} | skipped {s} | avg hold {(T.x-T.d).dt.days.mean():.1f}d", flush=True)
print("RECYCLE SIM DONE")
