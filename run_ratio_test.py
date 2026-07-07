"""Put ratio spread (buy 1x ~30D put, sell 2x 16D put, same expiry) vs the
validated single 16D short put — same signals (bb_2sd + five_day_low, uptrend),
D+1 entry, exits 50% of net credit / 21 DTE, no stops. ES + GC, $0 data."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep

def ratio(root, e, pp, iv):
    mult = gx.FUT_SPECS[root]["mult"]
    lp = gx.select_delta_option(root, e, iv, kind="put", target_delta=0.30)
    sp = gx.select_delta_option(root, e, iv, kind="put", target_delta=0.16)
    if lp is None or sp is None or lp.expiration != sp.expiration: return None
    if lp.strike <= sp.strike: return None
    lpath = gx.get_option_path(lp.raw_symbol, e, lp.expiration).set_index("date")["mid"]
    spath = gx.get_option_path(sp.raw_symbol, e, sp.expiration).set_index("date")["mid"]
    if e not in lpath.index or e not in spath.index: return None
    c0 = 2*float(spath.loc[e]) - float(lpath.loc[e])       # net credit (short 2, long 1)
    if c0 <= 0: return None
    ls, ll, worst = float(spath.loc[e]), float(lpath.loc[e]), 0.0
    days = pp.loc[e:sp.expiration].index
    xd, xv, reason = days[-1], None, "expiry"
    for dt in days[1:]:
        if dt in spath.index: ls = float(spath.loc[dt])
        if dt in lpath.index: ll = float(lpath.loc[dt])
        v = 2*ls - ll
        worst = min(worst, (c0 - v)*mult)
        dte = (sp.expiration - dt).days
        if v <= 0.5*c0: xd, xv, reason = dt, v, "tp_50"; break
        if dte <= 21:   xd, xv, reason = dt, v, "t_21dte"; break
    if xv is None:
        F = float(pp.loc[xd,"close"])
        xv = 2*max(sp.strike-F,0.0) - max(lp.strike-F,0.0)
    tick = gx.FUT_SPECS[root].get("opt_tick_usd", 10.0)
    pnl = (c0 - xv)*mult - 6*tick
    return dict(e=e, x=xd, pnl=pnl, worst=worst, reason=reason)

for root in ("ES","GC"):
    cont = gx.get_continuous(root, "2012-01-01", "2026-06-30")
    pp = _prep(cont); idx = pp.index
    bb = (pp["close"] <= pp["bb_lower"]) & pp["trend_up"]
    fdl = (pp["close"] <= pp["close"].rolling(5).min().shift(1)) & pp["trend_up"]
    sig = bb | fdl
    rows=[]
    for d in idx[sig]:
        pos = idx.searchsorted(d)+1
        if pos >= len(idx): continue
        e = idx[pos]
        iv = float(pp.loc[d,"rvol20"]) if pd.notna(pp.loc[d,"rvol20"]) else 0.25
        try:
            r = ratio(root, e, pp, iv)
            if r: rows.append(r)
        except Exception: pass
    t = pd.DataFrame(rows)
    if len(t):
        print(f"{root} put-ratio 1x2: n={len(t)} win%={100*(t.pnl>0).mean():.0f} "
              f"$/tr=${t.pnl.mean():,.0f} tot=${t.pnl.sum():,.0f} worst=${t.pnl.min():,.0f} "
              f"MAEp95=${t.worst.quantile(0.05):,.0f}", flush=True)
        print(f"  exits: {t.reason.value_counts().to_dict()}", flush=True)
print("RATIO TEST DONE")
