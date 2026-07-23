#!/usr/bin/env python
"""Edge test: forecasted IV (implied) vs the realized vol that actually followed.

Implied vol IS the market's forecast of future realized vol. The vol-seller's
edge exists only if that forecast is biased HIGH — i.e. iv45 today > the realized
vol over the next ~21 trading days (our hold horizon). This measures exactly that
gap (the *materialized* VRP), pooled and conditioned on our gate states — pure IV
math, no option pricing needed.

  forecast      = iv45 (today's ~45d ATM implied)
  realized_fwd  = annualized realized vol over the NEXT 21 trading days
  edge (pts)    = (forecast - realized_fwd) * 100   > 0 => seller's edge

Gate conditions tested (do they SHARPEN the edge?):
  rich   iv_rank >= 0.50      falling  slope5 <= 0      cheap  iv_rank <= 0.30

Usage: python forecast_vs_realized.py [SYM ...]
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

DIR = os.path.join("data_cache", "iv_series", "stocks")
DEFAULT = ["MSFT", "AAPL", "NVDA", "JPM", "XOM"]
HORIZON = 21   # trading days ~ the 50%/21DTE hold


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    logret = np.log(df["spot"] / df["spot"].shift(1))
    # realized vol over the NEXT HORIZON days (forward-looking), annualized
    fwd = logret.shift(-1).rolling(HORIZON).std() * np.sqrt(252)
    df["rv_fwd"] = fwd.shift(-(HORIZON - 1))     # align to signal day
    df["edge"] = (df["iv45"] - df["rv_fwd"]) * 100
    return df.dropna(subset=["edge"])


def line(name: str, s: pd.Series) -> dict:
    return dict(cell=name, n=len(s), edge_mean=round(s.mean(), 2),
                edge_med=round(s.median(), 2), win_pct=round(100 * (s > 0).mean(), 1))


def main() -> int:
    syms = sys.argv[1:] or DEFAULT
    have = [s for s in syms if os.path.exists(os.path.join(DIR, f"{s}.parquet"))]
    if not have:
        print("no IV series — run build_stock_iv_series.py first"); return 1
    frames = {s: enrich(pd.read_parquet(os.path.join(DIR, f"{s}.parquet"))) for s in have}

    print(f"Forecasted IV vs realized-ahead ({HORIZON}d fwd), {len(have)} names\n")
    print(f"{'cell':<14}{'n':>6}{'edge_mean':>11}{'edge_med':>10}{'win%':>8}")
    for s in have:
        r = line(s, frames[s]["edge"])
        print(f"{r['cell']:<14}{r['n']:>6}{r['edge_mean']:>11}{r['edge_med']:>10}{r['win_pct']:>8}")

    alld = pd.concat(frames.values())
    print("\n================ POOLED EDGE ================")
    base = line("ALL days", alld["edge"])
    print(f"unconditional : mean {base['edge_mean']:+.2f} pts, median {base['edge_med']:+.2f}, "
          f"forecast>outcome {base['win_pct']:.0f}% of days")
    # does the gate sharpen it?
    for tag, mask in [("rich (rank>=.5)", alld["iv_rank"] >= 0.50),
                      ("falling (slope5<=0)", alld["slope5_pts"] <= 0),
                      ("rich & falling", (alld["iv_rank"] >= 0.50) & (alld["slope5_pts"] <= 0)),
                      ("cheap (rank<=.3)", alld["iv_rank"] <= 0.30)]:
        sub = alld.loc[mask, "edge"]
        if len(sub):
            print(f"  {tag:<22}: mean {sub.mean():+6.2f} pts  win {100*(sub>0).mean():4.0f}%  (n={len(sub)})")
    print("\nRead: positive = implied over-forecasts realized -> vol-seller's edge. "
          "If 'rich/falling' beats unconditional, the gate earns its keep on pure IV.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
