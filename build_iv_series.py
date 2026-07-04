#!/usr/bin/env python
"""Build a daily ATM-IV series for a futures market from CME settlements.

Method (one pull per month, plan-covered $0):
  for each month: definitions on the first trading day (usually cached)
    -> expiry nearest 40 DTE -> ATM strike at that day's future price
    -> pull that option's settlements for the whole month
    -> imply Black-76 IV daily against the underlying future's settle path.
Output: data_cache/iv_series/<ROOT>.parquet  [date, iv, F, strike, dte]
plus derived dials: iv_rank (252d percentile), rv20, spread (iv-rv), slope5.

Usage: python build_iv_series.py CL [NG GC ...]
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from src.otbt.pricing import glbx_options as gx
from src.otbt.pricing.blackscholes import b76_price
from src.otbt.signals.indicators import realized_vol

OUT_DIR = os.path.join("data_cache", "iv_series")


def build(root: str, start="2012-01-01", end="2025-06-30") -> pd.DataFrame:
    cont = gx.get_continuous(root, start, end)
    if cont.empty:
        raise SystemExit(f"no continuous data for {root}")
    months = pd.period_range(cont.index.min(), cont.index.max(), freq="M")
    rows = []
    for m in months:
        days = cont.loc[str(m)].index
        if len(days) == 0:
            continue
        d0 = days[0]
        defs = gx.get_option_definitions(root, d0)
        if defs.empty:  # try a couple more days (holidays etc.)
            for alt in days[1:3]:
                defs = gx.get_option_definitions(root, alt)
                if not defs.empty:
                    d0 = alt
                    break
        if defs.empty:
            continue
        puts = defs[defs["instrument_class"] == "P"].copy()
        puts["dte"] = (puts["expiration"].dt.normalize() - d0).dt.days
        puts = puts[(puts["dte"] >= 25) & (puts["dte"] <= 75)]
        if puts.empty:
            continue
        exp = puts.iloc[(puts["dte"] - 40).abs().argsort().iloc[0]]["dte"]
        pe = puts[puts["dte"] == exp]
        F0 = float(cont.loc[d0, "close"])
        row = pe.iloc[(pe["strike_price"] - F0).abs().argsort().iloc[0]]
        sym, K = str(row["raw_symbol"]), float(row["strike_price"])
        expiration = pd.Timestamp(row["expiration"]).normalize()
        und = str(row["underlying"])

        opt = gx.get_option_path(sym, days[0], days[-1])
        if opt.empty:
            continue
        opt = opt.set_index("date")["mid"]
        fut = gx.get_symbol_daily(und, days[0], days[-1])
        fut = fut.set_index("date")["mid"] if not fut.empty else cont["close"]

        for d in days:
            if d not in opt.index:
                continue
            px = float(opt.loc[d])
            F = float(fut.loc[d]) if d in fut.index else float(cont.loc[d, "close"])
            T = max((expiration - d).days, 1) / 365.0
            if px <= 0 or F <= 0:
                continue
            try:
                iv = brentq(lambda s: b76_price(F, K, T, s, kind="put") - px,
                            1e-3, 5.0, maxiter=100)
            except (ValueError, RuntimeError):
                continue
            if 0.02 < iv < 3.0:
                rows.append((d, iv, F, K, (expiration - d).days))
        print(f"{root} {m}: ok ({len(rows)} pts total)", flush=True)

    s = pd.DataFrame(rows, columns=["date", "iv", "F", "strike", "dte"]) \
        .drop_duplicates("date").set_index("date").sort_index()
    # dials
    s["iv_rank"] = s["iv"].rolling(252, min_periods=100).apply(
        lambda w: (w.iloc[-1] >= w).mean())
    rv = realized_vol(cont["close"], 20)
    s["rv20"] = rv.reindex(s.index)
    s["spread"] = s["iv"] - s["rv20"]
    s["slope5"] = s["iv"].diff(5)
    os.makedirs(OUT_DIR, exist_ok=True)
    s.reset_index().to_parquet(os.path.join(OUT_DIR, f"{root}.parquet"))
    print(f"{root}: {len(s)} daily IV points "
          f"({s.index.min().date()} -> {s.index.max().date()}) saved.")
    return s


if __name__ == "__main__":
    for r in (sys.argv[1:] or ["CL"]):
        build(r)
