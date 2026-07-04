#!/usr/bin/env python
"""Lab batch: run METHOD x STRUCTURE combos on a futures market, save to DB.

Usage: python run_lab_batch.py CL short_strangle bb_2sd bounce_100ema ...
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import generate_signals
from src.otbt.signals.baseline import generate_baseline
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

root, structure = sys.argv[1], sys.argv[2]
methods = sys.argv[3:] or ["bb_2sd", "bounce_100ema", "bb_20sma", "five_day_low"]

cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
all_led = generate_signals({root: cont})
base_led = generate_baseline({root: cont})

frames = []
for m in methods:
    led = base_led if m == "vrp_baseline" else all_led[all_led["signal_type"] == m]
    led = led[led["iv_proxy"].notna()]
    print(f"{m}: {len(led)} signals", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(gx.simulate_structure, root, s["date"], cont, structure,
                          float(s["iv_proxy"]), signal_type=m)
                for _, s in led.iterrows()]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                results.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(led)}", flush=True)
    if results:
        frames.append(pd.DataFrame([r.__dict__ for r in results]))

if not frames:
    print("No trades priced.")
    sys.exit(0)
rdf = pd.concat(frames, ignore_index=True)
s = summarize(rdf)
rid = db.save_run(rdf, s, phase=f"lab_{root}_{structure}", universe=[root],
                  start="2012-01-01", end="2025-06-30",
                  created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  notes=f"Lab batch: {structure} on {root} for {methods}")
pd.set_option("display.width", 200)
print(f"\n=== {root} x {structure} (run_id={rid}, $/1-lot, net) ===\n")
print(s.to_string(index=False))
print(f"\nTrades: {len(rdf)} | avg credit ${rdf['entry_credit'].mean():,.0f}")
