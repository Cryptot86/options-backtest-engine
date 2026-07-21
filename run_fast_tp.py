"""Time-conditional TP test: (a) flat 50%/21DTE (law), (b) 40% if hit <=5 days
else 50%/21DTE (TJ's rule), (c) flat 40%. ES 16d puts, cached paths, $0."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep

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
        if e not in p.index: continue
        paths.append((e, S, p, float(p.loc[e])))
    except Exception: pass
print(f"paths ready: {len(paths)}", flush=True)
def run(mode):
    out=[]
    for e,S,p,c0 in paths:
        if c0<=0: continue
        days = pp.loc[e:S.expiration].index
        xv=None
        for n,dt in enumerate(days[1:],1):
            if dt in p.index:
                v=float(p.loc[dt]); dte=(S.expiration-dt).days
                fast_ok = (mode=="fast40" and n<=5 and v<=0.6*c0)
                tp = 0.5*c0 if mode!="flat40" else 0.6*c0
                if fast_ok or v<=tp: xv=v; break
                if dte<=21: xv=v; break
        if xv is None:
            F=float(pp.loc[days[-1],"close"]); xv=max(S.strike-F,0.0)
        out.append((c0-xv)*50-2*12.5)
    s=pd.Series(out)
    return len(s),100*(s>0).mean(),s.mean(),s.sum(),s.min()
for mode,label in (("flat50","flat 50%/21 (law)"),("fast40","40% if <=5d, else 50%/21"),("flat40","flat 40%/21")):
    n,w,a,t,mn = run(mode)
    print(f"{label:>26}: n={n} win%={w:.0f} $/tr=${a:,.0f} tot=${t:,.0f} worst=${mn:,.0f}", flush=True)
print("FAST TP DONE")
