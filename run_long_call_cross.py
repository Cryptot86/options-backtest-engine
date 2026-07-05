"""Buy an ATM call on each fresh 10x100 bullish cross (D+1). $0 - GLBX only."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from src.otbt.pricing import glbx_options as gx
from src.otbt.pricing.glbx_options import FutTradeResult
from src.otbt.signals.engine import _prep
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def long_call(root, entry_date, cont, iv):
    mult = gx.FUT_SPECS[root]["mult"]
    tick = gx.FUT_SPECS[root].get("opt_tick_usd", 10.0)
    fee = 0.75
    sel = gx.select_delta_option(root, entry_date, iv, kind="call", target_delta=0.50)
    if sel is None: return None
    p = gx.get_option_path(sel.raw_symbol, entry_date, sel.expiration)
    if p.empty: return None
    p = p.set_index("date")["mid"].sort_index()
    if entry_date not in p.index: return None
    e = float(p.loc[entry_date])
    if e <= 0: return None
    days = cont.loc[entry_date:sel.expiration].index
    last, worst = e, 0.0
    reason, xd, xp = "expiration", days[-1], None
    for dt in days[1:]:
        if dt in p.index: last = float(p.loc[dt])
        pnl = (last - e) * mult
        worst = min(worst, pnl)
        dte = (sel.expiration - dt).days
        if last >= 2 * e:  reason, xd, xp = "tp_100pct", dt, last; break
        if last <= 0.5 * e: reason, xd, xp = "sl_50pct", dt, last; break
        if dte <= 21:      reason, xd, xp = "t_21dte", dt, last; break
    if xp is None:
        Fx = float(cont.loc[xd, "close"])
        xp = max(Fx - sel.strike, 0.0)
    pnl = (xp - e) * mult - 2 * tick - 2 * fee
    return FutTradeResult(root, "long_call_cross", entry_date, pd.Timestamp(xd),
                          sel.strike, sel.dte, float("nan"), float("nan"),
                          -e * mult, pnl, pnl / (e * mult), worst,
                          int((pd.Timestamp(xd) - entry_date).days), reason)

rows = []
for root in ["ES", "GC", "CL", "NG", "6B", "6E"]:
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    if cont.empty: continue
    pp = _prep(cont)
    up = pp["trend_up"]; idx = pp.index
    bull = up & ~up.shift(1, fill_value=False)
    ent = []
    for d in idx[bull]:
        pos = idx.searchsorted(d) + 1
        if pos < len(idx): ent.append(idx[pos])
    print(f"{root}: {len(ent)} crosses", flush=True)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(long_call, root, d, pp,
                          float(pp.loc[d, "rvol20"]) if pd.notna(pp.loc[d, "rvol20"]) else 0.3)
                for d in ent]
        for f in as_completed(futs):
            try: r = f.result()
            except Exception: r = None
            if r: rows.append(r)

rdf = pd.DataFrame([r.__dict__ for r in rows])
print(f"\npriced: {len(rdf)}")
pd.set_option("display.width", 200)
g = rdf.groupby("symbol")["pnl"].agg(["size", "mean", "sum", "min", "max"]).round(0)
print("\n=== long ATM call on bullish cross, by market ===")
print(g.to_string())
print("\nexits:", rdf["exit_reason"].value_counts().to_dict())
s = summarize(rdf)
print(s.to_string(index=False))
rid = db.save_run(rdf, s, phase="long_call_cross", universe=["multi"],
                  start="2012-01-01", end="2025-06-30",
                  created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  notes="BUY 50d call on fresh 10x100 bull cross, D+1; TP+100%/SL-50%/21DTE")
print(f"saved run_id={rid}"); print("LONG CALL TEST DONE")
