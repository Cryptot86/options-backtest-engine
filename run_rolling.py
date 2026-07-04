#!/usr/bin/env python
"""Rolling vs mechanical, same signals (task #9 / H3 as-executed).

Usage: python run_rolling.py CL bb_2sd five_day_low
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from src.otbt.data import db
from src.otbt.pricing import glbx_options as gx
from src.otbt.pricing.rolling import simulate_rolling_chain
from src.otbt.signals.engine import generate_signals, _prep
from src.otbt.reporting.metrics import summarize

root = sys.argv[1] if len(sys.argv) > 1 else "CL"
methods = sys.argv[2:] or ["bb_2sd", "five_day_low"]

cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
prepped = _prep(cont)
led = generate_signals({root: cont})
led = led[led["signal_type"].isin(methods) & led["iv_proxy"].notna()]
print(f"{root}: {len(led)} signals ({methods}) -> rolling chains", flush=True)

results = []
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = [ex.submit(simulate_rolling_chain, root, s["date"], prepped,
                      s["signal_type"], float(s["iv_proxy"]))
            for _, s in led.iterrows()]
    for i, f in enumerate(as_completed(futs), 1):
        try:
            r = f.result()
        except Exception:
            r = None
        if r:
            results.append(r)
        if i % 50 == 0:
            print(f"  {i}/{len(led)}", flush=True)

rdf = pd.DataFrame([r.__dict__ for r in results])
if rdf.empty:
    print("no chains priced"); sys.exit(0)
s = summarize(rdf)
rid = db.save_run(rdf, s, phase=f"rolling_{root}", universe=[root],
                  start="2012-01-01", end="2025-06-30",
                  created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  notes="Tom rolling defense: roll out same strike at 21DTE, "
                        "chain=ONE trade, target 50% of cumulative credits")
pd.set_option("display.width", 200)
print(f"\n=== {root} ROLLING chains (run_id={rid}) ===")
print(s.to_string(index=False))
print("\nexit reasons:"); print(rdf["exit_reason"].value_counts().to_string())
print(f"\ntotal ${rdf['pnl'].sum():,.0f} | worst chain ${rdf['pnl'].min():,.0f} "
      f"| worst chain MAE ${rdf['mae'].min():,.0f} | avg days {rdf['days_held'].mean():.0f}")
