"""Delta sweep: sell 20d / 25d puts vs the 16d baseline. ES + NQ, D+1,
standard exits (50%/21DTE). $0 GLBX."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep

def trade(root, e, pp, iv, delta):
    mult = gx.FUT_SPECS[root]["mult"]
    S = gx.select_delta_option(root, e, iv, kind="put", target_delta=delta)
    if S is None: return None
    p = gx.get_option_path(S.raw_symbol, e, S.expiration)
    if p.empty: return None
    p = p.set_index("date")["mid"]
    if e not in p.index: return None
    c0 = float(p.loc[e])
    if c0 <= 0: return None
    days = pp.loc[e:S.expiration].index
    xd, xv = days[-1], None
    for dt in days[1:]:
        if dt in p.index:
            v = float(p.loc[dt])
            dte = (S.expiration - dt).days
            if v <= 0.5*c0: xd, xv = dt, v; break
            if dte <= 21:   xd, xv = dt, v; break
    if xv is None:
        F = float(pp.loc[xd,"close"]); xv = max(S.strike - F, 0.0)
    tick = gx.FUT_SPECS[root].get("opt_tick_usd", 10.0)
    return (c0 - xv)*mult - 2*tick

for root in ("ES","NQ"):
    cont = gx.get_continuous(root, "2012-01-01", "2026-06-30")
    pp = _prep(cont); idx = pp.index
    bb = (pp["close"] <= pp["bb_lower"]) & pp["trend_up"]
    fdl = (pp["close"] <= pp["close"].rolling(5).min().shift(1)) & pp["trend_up"]
    sig = bb | fdl
    ents = []
    for d in idx[sig]:
        pos = idx.searchsorted(d) + 1
        if pos >= len(idx): continue
        iv = float(pp.loc[d,"rvol20"]) if pd.notna(pp.loc[d,"rvol20"]) else 0.2
        ents.append((idx[pos], iv))
    print(f"{root}: {len(ents)} entries", flush=True)
    for delta in (0.20, 0.25):
        res = []
        for e, iv in ents:
            try:
                r = trade(root, e, pp, iv, delta)
                if r is not None: res.append(r)
            except Exception: pass
        s = pd.Series(res)
        if len(s):
            print(f"  {root} {int(delta*100)}d: n={len(s)} win%={100*(s>0).mean():.0f} "
                  f"$/tr=${s.mean():,.0f} tot=${s.sum():,.0f} worst=${s.min():,.0f}", flush=True)
print("DELTA SWEEP DONE")
