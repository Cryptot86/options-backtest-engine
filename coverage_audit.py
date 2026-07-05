"""Full coverage audit: every tested strategy family, futures + equities.

For the latest run of each phase x universe: regenerate the signal set
independently, join against DB trades, report coverage % and diagnose misses
(offline/cached where possible). Writes reports/COVERAGE.md.
"""
from dotenv import load_dotenv; load_dotenv()
import os
os.environ["OTBT_OFFLINE"] = "1"   # audit is cache-only: never spends, never crashes on vendor errors
import pandas as pd
from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import generate_signals, generate_call_signals, _prep

runs = db.list_runs()
con = db._conn()

def latest(phase, uni):
    m = runs[(runs["phase"] == phase) & (runs["universe"] == uni)]
    return int(m.iloc[0]["run_id"]) if len(m) else None

def trades_for(rid):
    t = pd.read_sql(f"SELECT symbol, entry_date, signal_type FROM trades WHERE run_id={rid}", con)
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    return t

def shift1(dates, cal):
    pos = cal.searchsorted(dates) + 1
    return pd.Series([cal[p] if p < len(cal) else pd.NaT for p in pos])

def audit(label, rid, led, cal=None, lag=0):
    if rid is None or led.empty:
        return None
    led = led[led["iv_proxy"].notna()].copy()
    led["date"] = pd.to_datetime(led["date"])
    if lag and cal is not None:
        led["date"] = shift1(led["date"], cal).values
        led = led.dropna(subset=["date"])
    t = trades_for(rid)
    tk = set(t["symbol"].astype(str) + "|" + t["entry_date"].astype(str)
             + "|" + t["signal_type"].astype(str))
    led["k"] = (led["symbol"].astype(str) + "|" + led["date"].astype(str)
                + "|" + led["signal_type"].astype(str))
    led["priced"] = led["k"].isin(tk)
    n, p = len(led), int(led["priced"].sum())
    miss = led[~led["priced"]]
    # diagnose misses from cache (futures only)
    reasons = {}
    for _, m in miss.iterrows():
        sym = m["symbol"]
        if sym not in gx.FUT_SPECS:
            reasons["equity_unpriced"] = reasons.get("equity_unpriced", 0) + 1
            continue
        d = pd.Timestamp(m["date"]).normalize()
        try:
            defs = gx.get_option_definitions(sym, d)      # cached (offline)
        except Exception:
            reasons["defs_error"] = reasons.get("defs_error", 0) + 1
            continue
        if defs.empty:
            reasons["no_definitions"] = reasons.get("no_definitions", 0) + 1
            continue
        cls = "C" if "call" in str(m["signal_type"]) else "P"
        o = defs[defs["instrument_class"] == cls].copy()
        o["dte"] = (o["expiration"].dt.normalize() - d).dt.days
        w = o[((o["dte"] >= 30) & (o["dte"] <= 45)) | ((o["dte"] >= 40) & (o["dte"] <= 75))]
        if w.empty:
            reasons["no_expiry_in_window"] = reasons.get("no_expiry_in_window", 0) + 1
        else:
            reasons["price_missing_or_error"] = reasons.get("price_missing_or_error", 0) + 1
    return dict(family=label, run=rid, signals=n, priced=p,
                coverage=round(100 * p / max(n, 1), 1), reasons=reasons)

rows = []
FUT = ["ES", "GC", "CL", "NG", "6B", "6E"]
conts = {r: gx.get_continuous(r, "2012-01-01", "2025-06-30") for r in FUT}
put_leds = {r: generate_signals({r: conts[r]}) for r in FUT if not conts[r].empty}
call_leds = {r: generate_call_signals({r: conts[r]}) for r in ["NG", "CL"]}

for r in FUT:
    rows.append(audit(f"{r} puts (same-day)", latest("futures_glbx", r), put_leds[r]))
for r in ["CL", "NG", "ES", "GC"]:
    rows.append(audit(f"{r} puts (D+1)", latest("futures_glbx_lag1", r),
                      put_leds[r], conts[r].index, lag=1))
for r in ["NG", "CL"]:
    rows.append(audit(f"{r} calls (same-day)", latest("futures_glbx_calls", r), call_leds[r]))
    rows.append(audit(f"{r} calls (D+1)", latest("futures_glbx_calls_lag1", r),
                      call_leds[r], conts[r].index, lag=1))

# cross entries (run saved as universe='multi')
cr = []
for r in FUT:
    pp = _prep(conts[r]); up = pp["trend_up"]; idx = pp.index
    for cond, st_ in [(up & ~up.shift(1, fill_value=False), "cross_put"),
                      (~up & up.shift(1, fill_value=True), "cross_call")]:
        for d in idx[cond]:
            pos = idx.searchsorted(d) + 1
            if pos < len(idx):
                cr.append(dict(symbol=r, date=idx[pos], signal_type=st_,
                               iv_proxy=float(pp.loc[d, "rvol20"]) if pd.notna(pp.loc[d, "rvol20"]) else 0.3))
rows.append(audit("10x100 crosses (all fut)", latest("cross_entry", "multi"), pd.DataFrame(cr)))

# equities
for sym, start in [("MSFT", "2020-01-01"), ("AAPL", "2019-01-01")]:
    pxe = get_prices(sym, start, "2025-06-30")
    lede = generate_signals({sym: pxe})
    lede = lede[pd.to_datetime(lede["date"]) >= start]
    rows.append(audit(f"{sym} puts (same-day)", latest("phase1_realiv", sym), lede))

rows = [r for r in rows if r]
rep = pd.DataFrame(rows)[["family", "run", "signals", "priced", "coverage"]]
print(rep.to_string(index=False))
print("\nmiss reasons by family:")
for r in rows:
    if r["reasons"]:
        print(f"  {r['family']}: {r['reasons']}")

os.makedirs("reports", exist_ok=True)
with open("reports/COVERAGE.md", "w") as f:
    f.write("# Coverage Audit — every tested strategy family\n\n")
    f.write(f"*Generated 2026-07-05. Signals regenerated independently and "
            f"joined against DB trades.*\n\n")
    f.write(rep.to_markdown(index=False))
    f.write("\n\n## Miss reasons\n")
    for r in rows:
        if r["reasons"]:
            f.write(f"- **{r['family']}** (run {r['run']}): {r['reasons']}\n")
    tot_s = rep["signals"].sum(); tot_p = rep["priced"].sum()
    f.write(f"\n**TOTAL: {tot_p}/{tot_s} = {100*tot_p/tot_s:.1f}% coverage**\n")
print(f"\nTOTAL: {rep['priced'].sum()}/{rep['signals'].sum()} = "
      f"{100*rep['priced'].sum()/rep['signals'].sum():.1f}%")
print("saved reports/COVERAGE.md")
print("AUDIT DONE")
