#!/usr/bin/env python
"""Layer 1 driver: pull underlying prices, generate the signal ledger, and
report signal frequency per month (H12 viability check).

Usage:
    python run_signals.py                 # default equity/ETF universe
    python run_signals.py SPY QQQ NVDA    # explicit symbols
"""
from __future__ import annotations

import sys

import pandas as pd

from src.otbt.config import DEFAULT_EQUITY_UNIVERSE, START_DATE, END_DATE, OUTPUT_DIR
from src.otbt.data.prices import get_universe_prices
from src.otbt.signals.engine import generate_signals


def main(argv: list[str]) -> int:
    symbols = argv[1:] or DEFAULT_EQUITY_UNIVERSE
    print(f"Universe ({len(symbols)}): {', '.join(symbols)}")
    print(f"Window: {START_DATE} -> {END_DATE}\n")

    prices = get_universe_prices(symbols, str(START_DATE), str(END_DATE))
    if not prices:
        print("No price data — aborting.")
        return 1

    ledger = generate_signals(prices)
    if ledger.empty:
        print("No signals generated.")
        return 0

    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "signal_ledger.parquet")
    ledger.to_parquet(out_path)

    # Frequency: signals per month across the universe (H12).
    months = (pd.to_datetime(ledger["date"]).max()
              - pd.to_datetime(ledger["date"]).min()).days / 30.44
    print(f"Total signals: {len(ledger)}  over ~{months:.0f} months\n")

    summary = (ledger.groupby("signal_type")
               .agg(n=("date", "size"),
                    trend_up_pct=("trend_up", "mean"),
                    symbols=("symbol", "nunique"))
               .assign(per_month=lambda d: (d["n"] / months).round(2),
                       trend_up_pct=lambda d: (d["trend_up_pct"] * 100).round(0))
               .sort_values("n", ascending=False))
    print(summary.to_string())
    print(f"\nLedger written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
