#!/usr/bin/env python
"""Validate the IV-dependent CONFIRMED indicators against real per-name IV.

Our gate, name-gate, and straddle-day lights were validated using PROXIES
(VIX, or realized-vol standing in for name IV) because we had no per-name IV
series. Study 1 now gives us real IV. This checks the premises those indicators
rest on actually hold on real IV — the precondition before any study runs.

Checks (IV-only; no option re-pricing needed):
  A. VRP premise      : is IV > realized (vrp_pts>0) structurally? (the whole
                        selling program's foundation; the '3-green gate: paid')
  B. Gate 'rich'      : how often iv_rank >= 0.50 (the gate's rich condition)
  C. Straddle cheap   : how often iv_rank<=0.30 AND iv45<rv20 (the cheap-vol
                        light) -> should fire a sane few times/yr
  D. Name-gate light3 : on storm-cresting days (iv_rank>=0.5 AND slope5<=0),
                        does chain IV > RV (iv45>rv20)? -> validates TJ's manual
                        chain-IV check that light 3 automates

Usage: python validate_iv_indicators.py [SYM ...]
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

DIR = os.path.join("data_cache", "iv_series", "stocks")
DEFAULT = ["MSFT", "AAPL", "NVDA", "JPM", "XOM"]


def load(sym: str) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(DIR, f"{sym}.parquet"))


def stats(sym: str, df: pd.DataFrame) -> dict:
    yrs = (df.index.max() - df.index.min()).days / 365.25
    rich = df["iv_rank"] >= 0.50
    paid = df["vrp_pts"] > 0
    cheap = (df["iv_rank"] <= 0.30) & (df["iv45"] < df["rv20"])
    storm = (df["iv_rank"] >= 0.50) & (df["slope5_pts"] <= 0)
    storm_paid = storm & paid
    return dict(
        sym=sym, rows=len(df), yrs=round(yrs, 1),
        vrp_med=round(df["vrp_pts"].median(), 2),
        pct_paid=round(100 * paid.mean(), 1),
        pct_rich=round(100 * rich.mean(), 1),
        cheap_per_yr=round(cheap.sum() / yrs, 1),
        storm_days=int(storm.sum()),
        light3_hold=round(100 * storm_paid.sum() / max(storm.sum(), 1), 1),
    )


def main() -> int:
    syms = sys.argv[1:] or DEFAULT
    have = [s for s in syms if os.path.exists(os.path.join(DIR, f"{s}.parquet"))]
    if not have:
        print("no IV series found — run build_stock_iv_series.py first"); return 1

    rows = [stats(s, load(s)) for s in have]
    df = pd.DataFrame(rows)
    print(f"IV-indicator validation on {len(have)} names: {', '.join(have)}\n")
    print(df.to_string(index=False))

    # pooled premise checks
    all_df = pd.concat([load(s) for s in have])
    paid = (all_df["vrp_pts"] > 0)
    storm = (all_df["iv_rank"] >= 0.50) & (all_df["slope5_pts"] <= 0)
    light3 = 100 * (storm & paid).sum() / max(storm.sum(), 1)
    vrp_med = all_df["vrp_pts"].median()
    print("\n================ POOLED VERDICT ================")
    print(f"A. VRP premise (IV>RV)     : median {vrp_med:+.2f} pts, "
          f"{100*paid.mean():.0f}% of days paid  -> "
          f"{'CONFIRMED' if vrp_med > 0 else 'FAILS — premium not present'}")
    print(f"D. Name-gate light-3       : chain IV > RV on {light3:.0f}% of "
          f"storm-cresting days  -> "
          f"{'CONFIRMED' if light3 >= 60 else 'WEAK — manual check not reliably true'}")
    print(f"C. Straddle cheap-vol light: {df.cheap_per_yr.mean():.1f} days/yr avg "
          f"(sane if ~2-15/yr)")
    print("\nInterpretation: these confirm the vol-state PREMISES our gate / "
          "name-gate / straddle light rely on. P&L validation still needs the "
          "option-chain pull (Studies proper).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
