#!/usr/bin/env python
"""Phase-0 backtest driver.

Generates the technical signal ledger (H1-H5) + the H6 VRP baseline, simulates
every trade with the realized-vol proxy, and prints the per-hypothesis metrics
table with delta-vs-baseline.

Usage:
    python run_backtest.py                  # default equity/ETF universe
    python run_backtest.py SPY QQQ NVDA
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from src.otbt.config import DEFAULT_EQUITY_UNIVERSE, START_DATE, END_DATE, OUTPUT_DIR
from src.otbt.data.prices import get_universe_prices
from src.otbt.signals.engine import generate_signals, _prep
from src.otbt.signals.baseline import generate_baseline
from src.otbt.pricing.simulate import simulate_trade
from src.otbt.reporting.metrics import results_frame, summarize

# H3 bounce uses thesis-invalidation (close below 100-EMA) as an exit.
INVALIDATION_SIGNALS = {"bounce_100ema"}


def run(symbols):
    prices = get_universe_prices(symbols, str(START_DATE), str(END_DATE))
    prepped = {s: _prep(df) for s, df in prices.items()}

    ledger = generate_signals(prices)
    baseline = generate_baseline(prices)
    full = pd.concat([ledger, baseline], ignore_index=True)
    print(f"Signals: {len(ledger)} technical + {len(baseline)} baseline\n")

    results = []
    for _, sig in full.iterrows():
        df = prepped.get(sig["symbol"])
        if df is None:
            continue
        res = simulate_trade(
            df, pd.Timestamp(sig["date"]), sig["direction"],
            sig["signal_type"], sig["symbol"],
            invalidation_below_ema100=sig["signal_type"] in INVALIDATION_SIGNALS,
        )
        if res is not None:
            results.append(res)

    rdf = results_frame(results)
    baseline_exp = rdf[rdf["signal_type"] == "vrp_baseline"]["pnl"].mean()
    summary = summarize(rdf, baseline_expectancy=baseline_exp)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    rdf.to_parquet(os.path.join(OUTPUT_DIR, "trades.parquet"))
    summary.to_csv(os.path.join(OUTPUT_DIR, "summary.csv"), index=False)

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print("=== Phase-0 per-hypothesis results ($/contract, net of costs) ===\n")
    print(summary.to_string(index=False))
    print("\nNote: realized-vol proxy for IV -> dollar magnitudes approximate "
          "(~±17% per charter); direction/ranking reliable. worst_loss & mae_p95 "
          "are the tail metrics to watch.")
    return summary


if __name__ == "__main__":
    run(sys.argv[1:] or DEFAULT_EQUITY_UNIVERSE)
