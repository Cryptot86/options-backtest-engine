"""SHORT CALL test on stocks: 2-SD rally in DOWNTREND -> sell 16d call, D+1.
Pre-registered forecast: TSLA/NVDA lose badly, MSFT marginal. Real OPRA prices."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def short_call(sym, e, pp, iv):
    spot = float(pp.loc[e, "close"])
    sel = dbo.select_16d_modeled(sym, e, spot, iv, kind="call", target_delta=0.16)
    if sel is None: return None
    p = dbo.get_symbol_daily(sel.raw_symbol, e, sel.expiration)
    if p.empty: return None
    p = p.set_index("date")["mid"].sort_index()
    if e not in p.index or p.loc[e] <= 0: return None
    c0 = float(p.loc[e]); last = c0; worst = 0.0
    days = pp.loc[e:sel.expiration].index
    reason, xd, xp = "expiration", days[-1], None
    for dt in days[1:]:
        if dt in p.index: last = float(p.loc[dt])
        worst = min(worst, (c0-last)*100)
        dte = (sel.expiration - dt).days
        if last <= 0.5*c0: reason, xd, xp = "take_profit_50", dt, 0.5*c0; break
        if dte <= 21:      reason, xd, xp = "manage_21dte", dt, last; break
    if xp is None:
        xp = max(float(pp.loc[xd,"close"]) - sel.strike, 0.0)
    pnl = (c0 - xp)*100 - 6.0
    return dict(symbol=sym, signal_type="bb_2sd_call_eq", entry_date=e, exit_date=xd,
                strike=sel.strike, dte=sel.dte, entry_iv=float("nan"),
                entry_delta=float("nan"), entry_credit=c0*100, pnl=pnl,
                pnl_pct_credit=pnl/(c0*100), mae=worst,
                days_held=int((xd-e).days), exit_reason=reason)

rows = []
for sym in ("MSFT","TSLA","NVDA"):
    px = get_prices(sym, "2019-01-01", "2025-06-30")
    pp = _prep(px); idx = pp.index
    from src.otbt.signals import indicators as ind
    _, up20, _ = ind.bollinger(pp["close"], 20, 2.0)
    hit = (pp["close"] >= up20) & ~pp["trend_up"]
    entry = hit & ~hit.shift(1, fill_value=False)
    ents = []
    for d in idx[entry]:
        pos = idx.searchsorted(d)+1
        if pos < len(idx) and pd.notna(pp.loc[d,"rvol20"]):
            ents.append((idx[pos], float(pp.loc[d,"rvol20"])))
    print(f"{sym}: {len(ents)} call-sell signals (2-SD rally in downtrend)", flush=True)
    for e, iv in ents:
        for attempt in range(30):
            try:
                r = short_call(sym, e, pp, iv)
                if r: rows.append(r)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower():
                    print("BUDGET WAIT...", flush=True); _t.sleep(300)
                else: break
t = pd.DataFrame(rows)
if len(t):
    pd.set_option("display.width", 200)
    g = t.groupby("symbol")["pnl"].agg(["size","mean","sum","min"]).round(0)
    print(g.to_string())
    print(f"\npooled: n={len(t)} win%={100*(t.pnl>0).mean():.0f} "
          f"$/trade=${t.pnl.mean():,.0f} worst=${t.pnl.min():,.0f}")
    db.save_run(t, summarize(t), phase="equity_callsell", universe=sorted(t.symbol.unique()),
                start="2019-01-01", end="2025-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="SHORT 16d call on 2-SD rally in downtrend, D+1, stocks — forecast: fails")
print("EQUITY CALLSELL DONE")
