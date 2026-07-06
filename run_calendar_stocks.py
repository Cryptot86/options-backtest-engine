"""H14 stocks: ATM put calendar (sell ~30DTE / buy ~90DTE, same strike) when
VIX cheap (rank<=0.3 & VIX<SPY RV). Exits +40%/-50%/front-7DTE. Real OPRA."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.signals.indicators import realized_vol
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

vix = get_prices("^VIX","2017-01-01","2026-06-30")["close"]
spy = get_prices("SPY","2017-01-01","2026-06-30")["close"]
rank = vix.rolling(252).apply(lambda w:(w.iloc[-1]>=w).mean())
cheap = (rank<=0.3)&((vix-realized_vol(spy,20).reindex(vix.index)*100)<0)

def calendar(sym, e, pp):
    defs = dbo.get_definitions(sym, e)
    if defs.empty: return None
    o = defs[defs["instrument_class"]=="P"].copy()
    o["dte"] = (o["expiration"]-e).dt.days
    F = float(pp.loc[e,"close"])
    fr = o[(o.dte>=25)&(o.dte<=45)]; bk = o[(o.dte>=75)&(o.dte<=120)]
    if fr.empty or bk.empty: return None
    fdte = fr.iloc[(fr.dte-30).abs().argsort().iloc[0]].dte; fr = fr[fr.dte==fdte]
    K = float(fr.iloc[(fr.strike_price-F).abs().argsort().iloc[0]].strike_price)
    frow = fr[fr.strike_price==K].iloc[0]
    bk2 = bk[abs(bk.strike_price-K)<1e-6]
    if bk2.empty: return None
    brow = bk2.iloc[(bk2.dte-90).abs().argsort().iloc[0]]
    fexp = pd.Timestamp(frow.expiration).normalize()
    fp = dbo.get_symbol_daily(str(frow.raw_symbol), e, fexp)
    bp = dbo.get_symbol_daily(str(brow.raw_symbol), e, fexp)
    if fp.empty or bp.empty: return None
    fp=fp.set_index("date")["mid"]; bp=bp.set_index("date")["mid"]
    if e not in fp.index or e not in bp.index: return None
    d0 = float(bp.loc[e])-float(fp.loc[e])
    if d0<=0: return None
    lf,lb,worst = float(fp.loc[e]), float(bp.loc[e]), 0.0
    days = pp.loc[e:fexp].index
    reason,xd,xv = "front_expiry", days[-1], None
    for dt in days[1:]:
        if dt in fp.index: lf=float(fp.loc[dt])
        if dt in bp.index: lb=float(bp.loc[dt])
        v=lb-lf; worst=min(worst,(v-d0)*100)
        dte=(fexp-dt).days
        if v>=1.4*d0: reason,xd,xv="tp_40",dt,v; break
        if v<=0.5*d0: reason,xd,xv="sl_50",dt,v; break
        if dte<=7:    reason,xd,xv="front_7dte",dt,v; break
    if xv is None: xv = lb - max(K-float(pp.loc[xd,"close"]),0.0)
    return dict(symbol=sym, signal_type="cal_cheap_eq", entry_date=e, exit_date=xd,
                strike=K, dte=int(fdte), entry_iv=float("nan"), entry_delta=float("nan"),
                entry_credit=-d0*100, pnl=(xv-d0)*100-6.0, pnl_pct_credit=(xv-d0)/d0,
                mae=worst, days_held=int((xd-e).days), exit_reason=reason)

rows=[]
for sym in ("MSFT","TSLA","AAPL","META","GOOGL","AMZN"):
    pp=_prep(get_prices(sym,"2019-01-01","2026-06-30")); idx=pp.index
    ents,last=[],None
    for d in idx:
        if not bool(cheap.get(d,False)): continue
        pos=idx.searchsorted(d)+1
        if pos>=len(idx): continue
        e=idx[pos]
        if last is None or (e-last).days>=21: ents.append(e); last=e
    print(f"{sym}: {len(ents)} entries", flush=True)
    got=[]
    for e in ents:
        for a in range(20):
            try:
                r=calendar(sym,e,pp)
                if r: got.append(r); rows.append(r)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                else: break
    if got:
        t=pd.DataFrame(got)
        print(f"  -> n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} "
              f"tot=${t.pnl.sum():,.0f} worst=${t.pnl.min():,.0f}", flush=True)
if rows:
    t=pd.DataFrame(rows)
    db.save_run(t, summarize(t), phase="calendar_h14_stocks", universe=sorted(t.symbol.unique()),
                start="2019-01-01", end="2026-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="H14 stocks: ATM put calendar 30/90, VIX-cheap entries")
    print(f"\npooled: n={len(t)} win%={100*(t.pnl>0).mean():.0f} tot=${t.pnl.sum():,.0f}")
print("CALENDAR STOCKS DONE")
