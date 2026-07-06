"""Straddle DTE sweep on cheap-vol entries: 40 vs 60 vs 90 DTE. ES+CL, $0.
Same exits: +50% debit / -40% / 21 DTE remaining."""
from dotenv import load_dotenv; load_dotenv()
import os, pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep

def straddle(root, e, pp, iv, dte_t):
    mult = gx.FUT_SPECS[root]["mult"]
    cS = gx.select_delta_option(root, e, iv, kind="call", target_delta=0.50,
                                dte_min=dte_t-15, dte_max=dte_t+25, dte_target=dte_t)
    pS = gx.select_delta_option(root, e, iv, kind="put", target_delta=0.50,
                                dte_min=dte_t-15, dte_max=dte_t+25, dte_target=dte_t)
    if cS is None or pS is None or abs(cS.strike-pS.strike) > 1e-6*max(1,cS.strike): pass
    if cS is None or pS is None: return None
    cp = gx.get_option_path(cS.raw_symbol, e, cS.expiration)
    pq = gx.get_option_path(pS.raw_symbol, e, pS.expiration)
    if cp.empty or pq.empty: return None
    cp=cp.set_index("date")["mid"]; pq=pq.set_index("date")["mid"]
    if e not in cp.index or e not in pq.index: return None
    d0 = float(cp.loc[e])+float(pq.loc[e])
    if d0<=0: return None
    lc,lp = float(cp.loc[e]), float(pq.loc[e])
    days = pp.loc[e:cS.expiration].index
    xd, xv = days[-1], None
    for dt in days[1:]:
        if dt in cp.index: lc=float(cp.loc[dt])
        if dt in pq.index: lp=float(pq.loc[dt])
        v=lc+lp; dte=(cS.expiration-dt).days
        if v>=1.5*d0: xd,xv=dt,v; break
        if v<=0.6*d0: xd,xv=dt,v; break
        if dte<=21:   xd,xv=dt,v; break
    if xv is None:
        xv = abs(float(pp.loc[xd,"close"])-cS.strike)
    return (xv-d0)*mult - 4*13.0

for root in ("ES","CL"):
    cont = gx.get_continuous(root,"2012-01-01","2026-06-30")
    pp=_prep(cont); idx=pp.index
    dl = pd.read_parquet(f"data_cache/iv_series/{root}.parquet")
    dl["date"]=pd.to_datetime(dl["date"]); dl=dl.set_index("date")
    cheap = (dl["iv_rank"]<=0.3)&(dl["spread"]<0)
    ents,last=[],None
    for d in idx:
        if not bool(cheap.get(d,False)): continue
        pos=idx.searchsorted(d)+1
        if pos>=len(idx) or pd.isna(pp.iloc[pos-1]["rvol20"]): continue
        e=idx[pos]
        if last is None or (e-last).days>=21: ents.append((e,float(pp.loc[d,"rvol20"] if pd.notna(pp.loc[d,"rvol20"]) else 0.2))); last=e
    print(f"{root}: {len(ents)} cheap-vol entries", flush=True)
    for dte_t in (40, 60, 90):
        res=[]
        for e,iv in ents:
            try:
                r=straddle(root,e,pp,iv,dte_t)
                if r is not None: res.append(r)
            except Exception: pass
        s=pd.Series(res)
        if len(s):
            print(f"  DTE {dte_t}: n={len(s):3d} win%={100*(s>0).mean():4.0f} "
                  f"$/tr=${s.mean():7,.0f} tot=${s.sum():9,.0f} worst=${s.min():8,.0f}", flush=True)
print("DTE SWEEP DONE")
