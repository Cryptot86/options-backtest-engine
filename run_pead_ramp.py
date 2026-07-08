"""Pre-earnings vol ramp: buy ATM straddle ~7 trading days before earnings,
expiry just AFTER the event, exit the session BEFORE the announcement."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd, yfinance as yf
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def ramp(sym, e, xday, px):
    spot = float(px.loc[e,"close"]); iv=0.35
    legs=[]
    for kind in ("call","put"):
        O = dbo.select_16d_modeled(sym, e, spot, iv, dte_min=8, dte_max=45, dte_target=18,
                                   target_delta=0.50, kind=kind)
        if O is None or pd.Timestamp(O.expiration) <= xday: return None
        p = dbo.get_symbol_daily(O.raw_symbol, e, xday).set_index("date")["mid"]
        if e not in p.index: return None
        legs.append((O,p))
    d0 = sum(float(p.loc[e]) for _,p in legs)
    if d0<=0: return None
    v = 0.0
    for O,p in legs:
        pe = p[p.index<=xday]
        if pe.empty: return None
        v += float(pe.iloc[-1])
    return dict(symbol=sym, entry_date=e, exit_date=xday, strike=legs[0][0].strike,
                dte=int((pd.Timestamp(legs[0][0].expiration)-e).days),
                entry_iv=float("nan"), entry_delta=0.50, entry_credit=-d0*100,
                pnl=(v-d0)*100-4.0, pnl_pct_credit=(v-d0)/d0, mae=float("nan"),
                days_held=int((xday-e).days), exit_reason="pre_event_exit",
                signal_type="vol_ramp")

rows=[]
for sym in ("AAPL","MSFT","NVDA","META","GOOGL"):
    ed = yf.Ticker(sym).get_earnings_dates(limit=60)
    ed = ed.dropna(subset=["Reported EPS","EPS Estimate"])
    ed.index = pd.to_datetime(ed.index).tz_localize(None).normalize()
    ed = ed[(ed.index>="2019-06-01")&(ed.index<="2026-06-01")]
    px = get_prices(sym,"2019-01-01","2026-06-30"); idx = px.index
    for dt in ed.sort_index().index:
        ei = idx.searchsorted(dt)             # first session >= earnings date
        xi = ei - 1                           # exit: session BEFORE the event
        en = xi - 7                           # entry: ~7 trading days before exit
        if en < 0 or xi <= 0 or xi >= len(idx): continue
        for att in range(20):
            try:
                tr = ramp(sym, idx[en], idx[xi], px)
                if tr: rows.append(tr)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                else: print(f"ERR {sym} {idx[en].date()}: {ex}", flush=True); break
    done=[x for x in rows if x["symbol"]==sym]
    if done:
        t=pd.DataFrame(done)
        print(f"-> {sym}: n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} tot=${t.pnl.sum():,.0f} worst=${t.pnl.min():,.0f}", flush=True)
if rows:
    t=pd.DataFrame(rows)
    print(f"\n=== vol-ramp pooled: n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} tot=${t.pnl.sum():,.0f} ===")
    db.save_run(t, summarize(t), phase="pead_volramp", universe=sorted(t.symbol.unique()),
                start="2019-06-01", end="2026-06-01",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="Vol ramp: ATM straddle 7td before earnings, expiry after event, exit day before")
print("VOL RAMP DONE")
