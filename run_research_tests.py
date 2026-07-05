"""Tier-1 research candidates: Crisis-Peak Fade + Term-Structure Carry.
Each reports its own COVERAGE (signals vs priced). $0 — GLBX only."""
from dotenv import load_dotenv; load_dotenv()
import os, sys
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

IV_DIR = "data_cache/iv_series"
def dials(root, suffix=""):
    p = os.path.join(IV_DIR, f"{root}{suffix}.parquet")
    if not os.path.exists(p): return None
    d = pd.read_parquet(p); d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date").sort_index()

def d1(cal, d):
    pos = cal.searchsorted(pd.Timestamp(d)) + 1
    return cal[pos] if pos < len(cal) else None

def run_sim(root, entries, kind_fn, label, phase, structure=None):
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    pp = _prep(cont)
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        if structure:
            futs = [ex.submit(gx.simulate_structure, root, d, pp, structure, iv, signal_type=label)
                    for d, iv, _ in entries]
        else:
            futs = [ex.submit(gx.simulate_fut_trade, root, d, pp, label, iv, kind=k)
                    for d, iv, k in entries]
        for f in as_completed(futs):
            try: r = f.result()
            except Exception: r = None
            if r: results.append(r)
    cov = 100 * len(results) / max(len(entries), 1)
    print(f"{root} {label}: COVERAGE {len(results)}/{len(entries)} = {cov:.0f}%", flush=True)
    return results

# ============ 1) CRISIS-PEAK FADE ============
print("@@@ CRISIS-PEAK FADE @@@", flush=True)
all_res = []
for root in ["ES", "CL", "GC", "NG"]:
    dv = dials(root)
    if dv is None: print(f"{root}: no dials"); continue
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    cal = cont.index
    rank_hi10 = dv["iv_rank"].rolling(10, min_periods=1).max()
    fell3 = (dv["iv"].diff() < 0) & (dv["iv"].diff().shift(1) < 0) & (dv["iv"].diff().shift(2) < 0)
    trig = (rank_hi10 >= 0.90) & fell3
    days, last = [], None
    for d in dv.index[trig.fillna(False)]:
        e = d1(cal, d)
        if e is None: continue
        if last is None or (e - last).days >= 5:
            days.append((e, float(dv.loc[d, "iv"]), "put")); last = e
    print(f"{root}: {len(days)} crisis-fade triggers", flush=True)
    all_res += run_sim(root, days, None, f"crisis_fade", "crisis_fade",
                       structure="crisis_fade_spread")
if all_res:
    rdf = pd.DataFrame([r.__dict__ for r in all_res])
    pd.set_option("display.width", 200)
    g = rdf.groupby("symbol")["pnl"].agg(["size","mean","sum","min"]).round(0)
    print(g.to_string()); print(summarize(rdf).to_string(index=False))
    db.save_run(rdf, summarize(rdf), phase="crisis_fade", universe=["multi"],
                start="2012-01-01", end="2025-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="post-panic fade: rank>=.9 in last 10d + IV down 3 days; 25/5d put spread")

# ============ 2) TERM-STRUCTURE CARRY ============
print("@@@ TERM CARRY @@@", flush=True)
all_res = []
for root in ["ES", "GC", "CL"]:
    front, back = dials(root), dials(root, "_90")
    if front is None or back is None:
        print(f"{root}: missing 90d series"); continue
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    pp = _prep(cont); cal = cont.index
    j = front[["iv", "slope5"]].join(back["iv"].rename("iv90"), how="inner")
    j["slope_ts"] = j["iv"] - j["iv90"]
    j["pct"] = j["slope_ts"].rolling(504, min_periods=252).apply(lambda w: (w.iloc[-1] >= w).mean())
    trig = (j["pct"] <= 0.20) & (j["slope5"] <= 0)
    days, last = [], None
    for d in j.index[trig.fillna(False)]:
        e = d1(cal, d)
        if e is None or e not in pp.index: continue
        if last is None or (e - last).days >= 7:
            k = "put" if bool(pp.loc[e, "trend_up"]) else "call"   # with-trend
            days.append((e, float(j.loc[d, "iv"]), k)); last = e
    print(f"{root}: {len(days)} term-carry triggers", flush=True)
    all_res += run_sim(root, days, None, "term_carry", "term_carry")
if all_res:
    rdf = pd.DataFrame([r.__dict__ for r in all_res])
    g = rdf.groupby(["symbol"])["pnl"].agg(["size","mean","sum","min"]).round(0)
    print(g.to_string()); print(summarize(rdf).to_string(index=False))
    db.save_run(rdf, summarize(rdf), phase="term_carry", universe=["multi"],
                start="2012-01-01", end="2025-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="steep-contango carry: (IV40-IV90) pctile<=20 + slope5<=0, with-trend 16d")
print("RESEARCH TESTS DONE")
