"""Book strategy v1 (gamma-scalp prerequisite): BUY ATM straddle when vol CHEAP.
Variants: (a) cheap-vol day entry (inverse gate), (b) HYBRID: fresh 10x100 cross
(either direction) AND vol cheap [user's mix-our-entry idea].
Exits: +50% debit / -40% / 21 DTE. ES+GC ($0) then MSFT+TSLA (small $)."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.signals.indicators import realized_vol
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db
from src.otbt.pricing import glbx_options as gx
from src.otbt.pricing import databento_options as dbo

def straddle(sym, e, pp, iv, fut):
    mult = gx.FUT_SPECS[sym]["mult"] if fut else 100
    spot = float(pp.loc[e,"close"])
    if fut:
        cS = gx.select_delta_option(sym, e, iv, kind="call", target_delta=0.50)
        pS = gx.select_delta_option(sym, e, iv, kind="put",  target_delta=0.50)
        get = gx.get_option_path
    else:
        cS = dbo.select_16d_modeled(sym, e, spot, iv, kind="call", target_delta=0.50)
        pS = dbo.select_16d_modeled(sym, e, spot, iv, kind="put",  target_delta=0.50)
        get = dbo.get_symbol_daily
    if cS is None or pS is None: return None
    cp = get(cS.raw_symbol, e, cS.expiration); pq = get(pS.raw_symbol, e, pS.expiration)
    if cp.empty or pq.empty: return None
    cp = cp.set_index("date")["mid"]; pq = pq.set_index("date")["mid"]
    if e not in cp.index or e not in pq.index: return None
    d0 = float(cp.loc[e]) + float(pq.loc[e])
    if d0 <= 0: return None
    lc, lp, worst = float(cp.loc[e]), float(pq.loc[e]), 0.0
    days = pp.loc[e:cS.expiration].index
    reason, xd, xv = "expiration", days[-1], None
    for dt in days[1:]:
        if dt in cp.index: lc = float(cp.loc[dt])
        if dt in pq.index: lp = float(pq.loc[dt])
        v = lc + lp
        worst = min(worst, (v-d0)*mult)
        dte = (cS.expiration - dt).days
        if v >= 1.5*d0: reason, xd, xv = "tp_50pct", dt, v; break
        if v <= 0.6*d0: reason, xd, xv = "sl_40pct", dt, v; break
        if dte <= 21:   reason, xd, xv = "t_21dte", dt, v; break
    if xv is None:
        Fx = float(pp.loc[xd,"close"])
        xv = abs(Fx - cS.strike)
    pnl = (xv - d0)*mult - 4*3.0
    return dict(symbol=sym, entry_date=e, exit_date=xd, strike=cS.strike, dte=cS.dte,
                entry_iv=float("nan"), entry_delta=float("nan"), entry_credit=-d0*mult,
                pnl=pnl, pnl_pct_credit=pnl/(d0*mult), mae=worst,
                days_held=int((xd-e).days), exit_reason=reason, signal_type="")

def run(sym, fut, start):
    if fut:
        px = gx.get_continuous(sym, start, "2025-06-30")
    else:
        px = get_prices(sym, start, "2025-06-30")
    pp = _prep(px); idx = pp.index
    rv = pp["rvol20"]
    if fut:
        try:
            dl = pd.read_parquet(f"data_cache/iv_series/{sym}.parquet")
            dl["date"]=pd.to_datetime(dl["date"]); dl=dl.set_index("date")
            cheap = (dl["iv_rank"]<=0.3)&(dl["spread"]<0)
        except Exception:
            return
        cheapmap = cheap
    else:
        vixs = get_prices("^VIX","2017-01-01","2025-06-30")["close"]
        spy = get_prices("SPY","2017-01-01","2025-06-30")["close"]
        rk = vixs.rolling(252).apply(lambda w:(w.iloc[-1]>=w).mean())
        cheapmap = (rk<=0.3)&((vixs-realized_vol(spy,20).reindex(vixs.index)*100)<0)
    up = pp["trend_up"]; cross = (up & ~up.shift(1,fill_value=False)) | (~up & up.shift(1,fill_value=True))
    for label, cond in (("straddle_cheap", pd.Series(idx.map(lambda d: bool(cheapmap.get(d,False))), index=idx)),
                        ("straddle_hybrid", cross & pd.Series(idx.map(lambda d: bool(cheapmap.get(d,False))), index=idx))):
        ents, last = [], None
        for d in idx[cond]:
            pos = idx.searchsorted(d)+1
            if pos >= len(idx) or pd.isna(rv.loc[d]): continue
            e = idx[pos]
            if last is None or (e-last).days >= (21 if label=="straddle_cheap" else 1):
                ents.append((e, float(rv.loc[d]))); last = e
        print(f"{sym} {label}: {len(ents)} entries", flush=True)
        rows=[]
        for e, iv in ents:
            for a in range(20):
                try:
                    r = straddle(sym, e, pp, iv, fut)
                    if r: r["signal_type"]=label; rows.append(r)
                    break
                except Exception as ex:
                    if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                    else: break
        if rows:
            t = pd.DataFrame(rows)
            print(f"  -> n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} "
                  f"tot=${t.pnl.sum():,.0f} worst=${t.pnl.min():,.0f}", flush=True)
            db.save_run(t, summarize(t), phase=f"straddle_{sym}", universe=[sym],
                        start=start, end="2025-06-30",
                        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        notes=f"long ATM straddle {label}, +50/-40/21DTE")
for sym, fut, st in (("ES",True,"2012-01-01"),("GC",True,"2012-01-01"),
                     ("MSFT",False,"2019-01-01"),("TSLA",False,"2019-01-01")):
    run(sym, fut, st)
print("STRADDLE TEST DONE")
