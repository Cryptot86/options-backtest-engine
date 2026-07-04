#!/usr/bin/env python
"""Vol-state edge analysis (H11 + honest H6).

Part A (--score): join each market's daily IV dials (rank / IV-RV spread /
5-day slope) onto its existing real-price trades and report expectancy by
vol-state — including the 3-green gate (rich + paid + stabilizing) vs rest.

Part B (--entry): run the GATE ITSELF as a standalone entry (no chart signal):
sell 16d put every day the gate is green (min 5-day gap), mechanical
50%/21DTE. The honest Tom/H6 baseline with a real gauge.

Usage:
    python analyze_vol_gate.py --score CL NG GC ES
    python analyze_vol_gate.py --entry CL
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from src.otbt.data import db
from src.otbt.pricing import glbx_options as gx
from src.otbt.reporting.metrics import summarize

IV_DIR = os.path.join("data_cache", "iv_series")

# Gate: rich (rank>=0.5) + paid (spread>0) + stabilizing (5d slope<=0)
def gate_green(d: pd.DataFrame) -> pd.Series:
    return (d["iv_rank"] >= 0.5) & (d["spread"] > 0) & (d["slope5"] <= 0)


def load_dials(root: str) -> pd.DataFrame:
    p = os.path.join(IV_DIR, f"{root}.parquet")
    if not os.path.exists(p):
        raise SystemExit(f"no IV series for {root} — run build_iv_series.py first")
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date").sort_index()


def latest_run_id(root: str) -> int | None:
    runs = db.list_runs()
    m = runs[(runs["phase"] == "futures_glbx") & (runs["universe"] == root)]
    return int(m.iloc[0]["run_id"]) if len(m) else None


def score(root: str) -> None:
    dials = load_dials(root)
    rid = latest_run_id(root)
    if rid is None:
        print(f"{root}: no futures_glbx run in DB"); return
    t = pd.read_sql(f"SELECT entry_date, pnl, mae FROM trades WHERE run_id={rid}",
                    db._conn())
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t = t.join(dials, on="entry_date", how="inner")
    if t.empty:
        print(f"{root}: no dial overlap"); return
    t["gate"] = gate_green(t)

    print(f"\n===== {root} (run {rid}, {len(t)} trades with dials) =====")
    for dim, cut in [("iv_rank", [0, .25, .5, .75, 1.0]),
                     ("spread", None), ("slope5", None)]:
        if cut:
            b = pd.cut(t[dim], cut)
        else:
            b = t[dim] > 0
        g = t.groupby(b, observed=True)["pnl"].agg(["size", "mean", "min"]).round(0)
        g.columns = ["n", "expectancy", "worst"]
        print(f"\nby {dim}:"); print(g.to_string())
    g = t.groupby("gate")["pnl"].agg(["size", "mean", "min"]).round(0)
    g.columns = ["n", "expectancy", "worst"]
    print("\n3-GREEN GATE (rich+paid+stabilizing):"); print(g.to_string())


def entry_backtest(root: str, min_gap=5) -> None:
    dials = load_dials(root)
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    from src.otbt.signals.engine import _prep
    prepped = _prep(cont)
    green = dials[gate_green(dials)].index
    entries, last = [], None
    for d in green:
        if d not in cont.index:
            continue
        if last is None or (d - last).days >= min_gap:
            entries.append(d); last = d
    print(f"{root}: {len(entries)} gate-green entries")
    iv_map = dials["iv"]

    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(gx.simulate_fut_trade, root, d, prepped, "vol_gate",
                          float(iv_map.loc[d])) for d in entries]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                results.append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(entries)}", flush=True)
    if not results:
        print("no trades priced"); return
    rdf = pd.DataFrame([r.__dict__ for r in results])
    s = summarize(rdf)
    rid = db.save_run(rdf, s, phase=f"vol_gate_{root}", universe=[root],
                      start="2012-01-01", end="2025-06-30",
                      created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      notes="gate-only entry: iv_rank>=.5 & spread>0 & slope5<=0, short 16d put")
    pd.set_option("display.width", 200)
    print(f"\n=== {root} GATE-ONLY short puts (run_id={rid}) ===")
    print(s.to_string(index=False))
    print(f"total ${rdf['pnl'].sum():,.0f} | worst ${rdf['pnl'].min():,.0f} "
          f"| worst MAE ${rdf['mae'].min():,.0f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "--score"
    if args and args[0].startswith("--"):
        mode, args = args[0], args[1:]
    for r in (args or ["CL"]):
        (score if mode == "--score" else entry_backtest)(r)
