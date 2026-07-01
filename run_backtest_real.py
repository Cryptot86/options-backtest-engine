#!/usr/bin/env python
"""Phase-1 real-IV backtest driver (cache-first Databento).

Runs the technical signals through the REAL option-price simulator. Every
Databento pull is cached, so re-runs cost $0. Prints billed-pull count so
you can watch spend.

Usage:
    python run_backtest_real.py SPY QQQ AAPL MSFT NVDA
    python run_backtest_real.py --limit 20 SPY QQQ   # cap trades per run
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from src.otbt.config import START_DATE, END_DATE, OUTPUT_DIR
from src.otbt.data.prices import get_universe_prices
from src.otbt.signals.engine import generate_signals, _prep
from src.otbt.pricing.simulate_real import simulate_real_trade
from src.otbt.reporting.metrics import summarize
from src.otbt.data import store

EQUITY_START = "2013-04-01"          # OPRA history begins here
INVALIDATION = {"bounce_100ema"}


def run(symbols, limit=None):
    store.reset_stats()
    prices = get_universe_prices(symbols, EQUITY_START, str(END_DATE))
    prepped = {s: _prep(df) for s, df in prices.items()}
    ledger = generate_signals(prices)
    ledger = ledger[pd.to_datetime(ledger["date"]) >= EQUITY_START]
    if limit:
        ledger = ledger.groupby("symbol").head(limit)
    print(f"Trades to price: {len(ledger)} (real IV, cache-first)\n")

    results = []
    for i, (_, sig) in enumerate(ledger.iterrows(), 1):
        df = prepped.get(sig["symbol"])
        if df is None or sig["iv_proxy"] is None:
            continue
        try:
            r = simulate_real_trade(
                sig["symbol"], sig["date"], df, sig["signal_type"],
                float(sig["iv_proxy"]),
                invalidation_below_ema100=sig["signal_type"] in INVALIDATION)
        except Exception as exc:
            print(f"[warn] {sig['symbol']} {sig['date']}: {exc}")
            r = None
        if r is not None:
            results.append(r)
        if i % 50 == 0:
            print(f"  {i}/{len(ledger)} priced | billed pulls so far: {store.STATS['misses']}")

    rdf = pd.DataFrame([r.__dict__ for r in results])
    if rdf.empty:
        print("No trades priced.")
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rdf.to_parquet(os.path.join(OUTPUT_DIR, "trades_real.parquet"))
    base = rdf[rdf["signal_type"] == "vrp_baseline"]["pnl"].mean() if "vrp_baseline" in rdf["signal_type"].values else None
    summary = summarize(rdf, baseline_expectancy=base)

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print("\n=== Phase-1 REAL-IV results ($/contract, net of costs) ===\n")
    print(summary.to_string(index=False))
    print(f"\nTrades priced: {len(rdf)} | avg entry credit ${rdf['entry_credit'].mean():.0f} "
          f"| avg entry IV {rdf['entry_iv'].mean():.1%} | avg |delta| {rdf['entry_delta'].abs().mean():.3f}")
    print(f"Cache: {store.STATS['misses']} billed pulls, {store.STATS['hits']} hits this run")


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    run(args or ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"], limit=limit)
