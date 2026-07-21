from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
out=[]
for root in ("ES","NQ"):
    cont = gx.get_continuous(root, "2012-01-01", "2026-06-30")
    pp = _prep(cont); idx = pp.index
    bb = (pp["close"] <= pp["bb_lower"]) & pp["trend_up"]
    fdl = (pp["close"] <= pp["close"].rolling(5).min().shift(1)) & pp["trend_up"]
    for d in idx[bb|fdl]:
        pos = idx.searchsorted(d)+1
        if pos>=len(idx): continue
        e = idx[pos]; iv = float(pp.loc[d,"rvol20"]) if pd.notna(pp.loc[d,"rvol20"]) else 0.2
        try:
            S = gx.select_delta_option(root, e, iv, kind="put", target_delta=0.20)
            if S is None: continue
            p = gx.get_option_path(S.raw_symbol, e, S.expiration).set_index("date")["mid"]
            if e not in p.index: continue
            c0=float(p.loc[e])
            if c0<=0: continue
            days=pp.loc[e:S.expiration].index; xd,xv=days[-1],None
            for dt in days[1:]:
                if dt in p.index:
                    v=float(p.loc[dt]); dte=(S.expiration-dt).days
                    if v<=0.5*c0: xd,xv=dt,v; break
                    if dte<=21: xd,xv=dt,v; break
            if xv is None:
                F=float(pp.loc[xd,"close"]); xv=max(S.strike-F,0.0)
            mult=gx.FUT_SPECS[root]["mult"]; tick=gx.FUT_SPECS[root].get("opt_tick_usd",10.0)
            out.append(dict(root=root,d=e,x=xd,pnl=(c0-xv)*mult-2*tick))
        except Exception: pass
pd.DataFrame(out).to_parquet("output/delta20_rows.parquet")
print("saved", len(out), "rows")
