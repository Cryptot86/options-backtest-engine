"""Long ATM call on 10x100 bullish cross — equities (real OPRA prices, D+1).
Exits: +100% / -50% / 21 DTE. Waits+retries on budget errors."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def long_call(sym, e, pp, iv):
    sel = dbo.select_16d_modeled(sym, e, float(pp.loc[e,"close"]), iv, kind="call",
                                 target_delta=0.50)
    if sel is None: return None
    p = dbo.get_symbol_daily(sel.raw_symbol, e, sel.expiration)
    if p.empty: return None
    p = p.set_index("date")["mid"].sort_index()
    if e not in p.index or p.loc[e] <= 0: return None
    d0 = float(p.loc[e]); last = d0; worst = 0.0
    days = pp.loc[e:sel.expiration].index
    reason, xd, xp = "expiration", days[-1], None
    for dt in days[1:]:
        if dt in p.index: last = float(p.loc[dt])
        worst = min(worst, (last-d0)*100)
        dte = (sel.expiration - dt).days
        if last >= 2*d0:  reason, xd, xp = "tp_100", dt, last; break
        if last <= 0.5*d0: reason, xd, xp = "sl_50", dt, last; break
        if dte <= 21:     reason, xd, xp = "t_21dte", dt, last; break
    if xp is None:
        xp = max(float(pp.loc[xd,"close"]) - sel.strike, 0.0)
    pnl = (xp - d0)*100 - 6.0
    return dict(symbol=sym, signal_type="long_call_cross", entry_date=e,
                exit_date=xd, strike=sel.strike, dte=sel.dte, entry_iv=float("nan"),
                entry_delta=float("nan"), entry_credit=-d0*100, pnl=pnl,
                pnl_pct_credit=pnl/(d0*100), mae=worst,
                days_held=int((xd-e).days), exit_reason=reason)

rows = []
for sym, start in [("MSFT","2019-01-01"),("TSLA","2019-01-01"),
                   ("COIN","2021-04-14"),("HOOD","2021-07-29")]:
    px = get_prices(sym, start, "2025-06-30")
    pp = _prep(px); idx = pp.index
    up = pp["trend_up"]; bull = up & ~up.shift(1, fill_value=False)
    ents = []
    for d in idx[bull]:
        pos = idx.searchsorted(d)+1
        if pos < len(idx) and pd.notna(pp.loc[d,"rvol20"]):
            ents.append((idx[pos], float(pp.loc[d,"rvol20"])))
    print(f"{sym}: {len(ents)} bullish crosses", flush=True)
    for e, iv in ents:
        for attempt in range(20):
            try:
                r = long_call(sym, e, pp, iv)
                if r: rows.append(r)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower():
                    print("BUDGET WAIT (bump cap ~$5)...", flush=True); _t.sleep(300)
                else:
                    break
t = pd.DataFrame(rows)
if len(t):
    pd.set_option("display.width",200)
    g = t.groupby("symbol")["pnl"].agg(["size","mean","sum","min","max"]).round(0)
    print(g.to_string())
    w,l = t[t.pnl>0], t[t.pnl<=0]
    print(f"\npooled: n={len(t)} win%={100*(t.pnl>0).mean():.0f} avgW=${w.pnl.mean():,.0f} "
          f"avgL=${l.pnl.mean():,.0f} W/L={abs(w.pnl.mean()/l.pnl.mean()):.2f} total=${t.pnl.sum():,.0f}")
    db.save_run(t, summarize(t), phase="equity_longcall", universe=sorted(t.symbol.unique()),
                start="2019-01-01", end="2025-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="BUY ATM call on 10x100 bull cross, D+1, +100/-50/21DTE, real OPRA prices")
print("EQUITY LONGCALL DONE")
