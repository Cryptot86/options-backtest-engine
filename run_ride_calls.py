"""TJ's ride-the-winner theory: buy ~120 DTE ATM call at bullish cross,
NO profit cap — exit ONLY on trend flip (10<100) or 21 DTE. Stocks."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

rows=[]
for sym, start in (("MSFT","2019-01-01"),("TSLA","2019-01-01"),("NVDA","2019-01-01"),("COIN","2021-04-14")):
    px = get_prices(sym, start, "2025-06-30")
    pp = _prep(px); idx = pp.index
    up = pp["trend_up"]; bull = up & ~up.shift(1, fill_value=False)
    ents=[]
    for d in idx[bull]:
        pos = idx.searchsorted(d)+1
        if pos < len(idx) and pd.notna(pp.loc[d,"rvol20"]):
            ents.append((idx[pos], float(pp.loc[d,"rvol20"])))
    print(f"{sym}: {len(ents)} crosses", flush=True)
    for e, iv in ents:
        for a in range(20):
            try:
                sel = dbo.select_16d_modeled(sym, e, float(pp.loc[e,"close"]), iv,
                                             kind="call", target_delta=0.50,
                                             dte_min=90, dte_max=180, dte_target=120)
                if sel is None: break
                p = dbo.get_symbol_daily(sel.raw_symbol, e, sel.expiration)
                if p.empty: break
                p = p.set_index("date")["mid"].sort_index()
                if e not in p.index or p.loc[e] <= 0: break
                d0 = float(p.loc[e]); last = d0; worst = 0.0
                days = pp.loc[e:sel.expiration].index
                reason, xd, xp = "expiration", days[-1], None
                for dt in days[1:]:
                    if dt in p.index: last = float(p.loc[dt])
                    worst = min(worst, (last-d0)*100)
                    dte = (sel.expiration - dt).days
                    if not bool(pp.loc[dt,"trend_up"]): reason, xd, xp = "trend_flip", dt, last; break
                    if dte <= 21: reason, xd, xp = "t_21dte", dt, last; break
                if xp is None:
                    xp = max(float(pp.loc[xd,"close"]) - sel.strike, 0.0)
                rows.append(dict(symbol=sym, signal_type="ride_call", entry_date=e,
                                 exit_date=xd, strike=sel.strike, dte=sel.dte,
                                 entry_iv=float("nan"), entry_delta=float("nan"),
                                 entry_credit=-d0*100, pnl=(xp-d0)*100-6.0,
                                 pnl_pct_credit=(xp-d0)/d0, mae=worst,
                                 days_held=int((xd-e).days), exit_reason=reason))
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                else: break
t = pd.DataFrame(rows)
if len(t):
    pd.set_option("display.width",200)
    g = t.groupby("symbol")["pnl"].agg(["size","mean","sum","min","max"]).round(0)
    print(g.to_string())
    w,l = t[t.pnl>0], t[t.pnl<=0]
    print(f"\npooled: n={len(t)} win%={100*(t.pnl>0).mean():.0f} avgW=${w.pnl.mean():,.0f} "
          f"avgL=${l.pnl.mean():,.0f} W/L={abs(w.pnl.mean()/l.pnl.mean()):.2f} tot=${t.pnl.sum():,.0f}")
    print("exits:", t.exit_reason.value_counts().to_dict())
    db.save_run(t, summarize(t), phase="ride_calls", universe=sorted(t.symbol.unique()),
                start="2019-01-01", end="2025-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="TJ ride theory: 120DTE ATM call at cross, exit ONLY trend-flip/21DTE, no cap")
print("RIDE CALLS DONE")
