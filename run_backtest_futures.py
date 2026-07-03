#!/usr/bin/env python
"""Futures-options backtest driver (GLBX, plan-covered -> $0 marginal cost).

Signals run on the continuous front-month series; trades are priced off real
option daily bars with Black-76. Results go to the SQLite DB.

Usage:
    python run_backtest_futures.py CL                    # full history
    python run_backtest_futures.py CL --start 2015-01-01
    python run_backtest_futures.py CL --limit 5          # validation slice
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from src.otbt.config import END_DATE
from src.otbt.data import db, store
from src.otbt.signals.engine import generate_signals, _prep
from src.otbt.pricing.glbx_options import get_continuous, simulate_fut_trade
from src.otbt.reporting.metrics import summarize

GLBX_START = "2012-01-01"            # options ohlcv solid from here
INVALIDATION = {"bounce_100ema"}
WORKERS = 16


def run(root: str, start=GLBX_START, limit=None, workers=WORKERS):
    store.reset_stats()
    cont = get_continuous(root, start, str(END_DATE))
    if cont.empty:
        print("No continuous futures data.")
        return
    print(f"{root} continuous: {len(cont)} days "
          f"({cont.index.min().date()} -> {cont.index.max().date()})", flush=True)

    prepped = _prep(cont)
    ledger = generate_signals({root: cont})
    ledger = ledger[pd.to_datetime(ledger["date"]) >= start]
    ledger = ledger[ledger["iv_proxy"].notna()]      # drop rvol warmup period
    if limit:
        ledger = ledger.head(limit)
    rows = [sig for _, sig in ledger.iterrows()]
    total = len(rows)
    print(f"Trades to price: {total} (GLBX real prices, cache-first, "
          f"{workers} workers)\n", flush=True)

    def _price(sig):
        try:
            return simulate_fut_trade(
                root, sig["date"], prepped, sig["signal_type"],
                float(sig["iv_proxy"]),
                invalidation_below_ema100=sig["signal_type"] in INVALIDATION)
        except Exception as exc:
            print(f"[warn] {sig['date']}: {exc}", flush=True)
            return None

    results, done, lock = [], 0, threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_price, sig) for sig in rows]
        for f in as_completed(futs):
            r = f.result()
            with lock:
                done += 1
                if r is not None:
                    results.append(r)
                if done % 50 == 0 or done == total:
                    print(f"  {done}/{total} | pulls: {store.STATS['misses']} "
                          f"| hits: {store.STATS['hits']}", flush=True)

    rdf = pd.DataFrame([r.__dict__ for r in results])
    if rdf.empty:
        print("No trades priced.")
        return
    summary = summarize(rdf)
    run_id = db.save_run(
        rdf, summary, phase="futures_glbx", universe=[root],
        start=str(start), end=str(END_DATE),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=f"GLBX {root} options, Black-76, model-picked 16d, plan-covered ($0)")

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(f"\n=== {root} futures-options results (run_id={run_id}, $/contract, net) ===\n")
    print(summary.to_string(index=False))
    print(f"\nTrades: {len(rdf)} | avg credit ${rdf['entry_credit'].mean():.0f} "
          f"| avg IV {rdf['entry_iv'].mean():.1%} | avg |delta| {rdf['entry_delta'].abs().mean():.3f}")
    print(f"Saved to DB (run_id={run_id}). "
          f"Pulls: {store.STATS['misses']} (plan-covered), hits: {store.STATS['hits']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = start = None
    if "--limit" in args:
        i = args.index("--limit"); limit = int(args[i + 1]); args = args[:i] + args[i + 2:]
    if "--start" in args:
        i = args.index("--start"); start = args[i + 1]; args = args[:i] + args[i + 2:]
    run(args[0] if args else "CL", start=start or GLBX_START, limit=limit)
