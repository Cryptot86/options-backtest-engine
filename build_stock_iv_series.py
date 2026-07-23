#!/usr/bin/env python
"""Study 1 — the crown jewel: per-name daily IV series from IVolatility.

The manifest's Study 1 ("daily ~45d ATM IV for the universe, max depth") that
unblocks Studies 2-5 and lights the scanner's dials. IVol's IVX endpoint returns
the whole constant-maturity term structure per day in ONE call, so this is fast
and needs no contract selection or Black-Scholes inversion (unlike the futures
build_iv_series.py, which had to imply IV from settlements).

Per name, per day we store the ATM term structure + the derived dials each
pending study needs:
  iv45      ~45d ATM IV (linear interp of 30d & 60d Mean)      -> the primary
  iv30/60/90, iv30_put                                         -> tenors + put side
  rv20      20d realized vol (annualized, from split-adjusted close)
  vrp_pts   (iv45 - rv20) * 100   -> Study 5 VRP-gap dial
  slope5_pts (iv45 - iv45[5]) *100 -> Study 2 name-IV slope dial (parked since 07-09)
  iv_rank   252d percentile of iv45 -> Study 3 crisis-peak / IVR
  term_pts  (iv30 - iv90) * 100    -> candidate #1 term-structure carry

Output: data_cache/iv_series/stocks/<SYMBOL>.parquet  [date index + columns above]

IVol basis note (see memory ivol-lab-validated): IV numbers are basis-independent;
RV is computed from stock-prices *adjusted* close so splits stay continuous. No
option-strike matching here, so the split gotcha never bites this pull.

Usage:
  python build_stock_iv_series.py                 # full 35-name universe, max depth
  python build_stock_iv_series.py MSFT AAPL --start 2015-01-01
  python build_stock_iv_series.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from src.otbt.pricing import ivol_client as iv

OUT_DIR = os.path.join("data_cache", "iv_series", "stocks")

# The FULL 35-stock universe (manifest, TJ 2026-07-22). Recent IPOs (ARM, COIN,
# PLTR, SMCI, HOOD, LYFT) simply return shorter history — max depth per name.
STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "CRM", "COST", "LLY", "UNH", "JNJ", "PFE", "JPM", "BAC", "WFC", "GS",
    "XOM", "CVX", "COP", "CAT", "DE", "BA", "HD", "MCD", "NKE", "DIS",
    "WMT", "C", "TSM", "PLTR", "COIN",
]


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Fetch a lowercased IVX column (they arrive like '30d iv mean')."""
    return pd.to_numeric(df[name], errors="coerce") if name in df.columns else pd.Series(dtype=float)


def _chunks(start: str, end: str, days: int = 360):
    """Yield (from, to) windows <= 1 year — the IVX/stock endpoints cap range at
    ~1yr and silently return zero rows beyond it."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    while s < e:
        c = min(s + pd.Timedelta(days=days), e)
        yield s.strftime("%Y-%m-%d"), c.strftime("%Y-%m-%d")
        s = c + pd.Timedelta(days=1)


def _pull_all(fn, symbol: str, start: str, end: str) -> pd.DataFrame:
    """Call a 1yr-capped endpoint across yearly chunks and stitch the history."""
    parts = [df for f, t in _chunks(start, end)
             if not (df := fn(symbol, f, t)).empty]
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True).drop_duplicates(subset="date")
    return out.set_index("date").sort_index()


def build(symbol: str, start: str, end: str) -> pd.DataFrame:
    # 1. IVX term structure (yearly chunks) — the IV side
    ivx = _pull_all(iv.iv_series, symbol, start, end)
    if ivx.empty:
        raise RuntimeError("no IVX rows")
    iv30 = _col(ivx, "30d iv mean")
    iv60 = _col(ivx, "60d iv mean")
    iv90 = _col(ivx, "90d iv mean")
    iv45 = iv30 + (45 - 30) / (60 - 30) * (iv60 - iv30)      # linear interp -> ~45d ATM
    frame = pd.DataFrame({
        "spot": _col(ivx, "price"),
        "iv30": iv30, "iv45": iv45, "iv60": iv60, "iv90": iv90,
        "iv30_put": _col(ivx, "30d iv put"),
    })

    # 2. stock prices (yearly chunks): RV20 from ADJUSTED close (split-continuous
    # returns) + the UNADJUSTED close = the as-traded basis that listed option
    # strikes live on. NOTE: IVX 'price' and stock 'close' are both split-
    # ADJUSTED (verified 2026-07-23: TSLA 2019 15.93 vs unadjusted 238.92) —
    # strike selection MUST use spot_unadj, never spot.
    px = _pull_all(iv.stock_ohlc, symbol, start, end)
    if not px.empty:
        close = pd.to_numeric(px["close"], errors="coerce")     # adjusted (split-continuous)
        logret = np.log(close / close.shift(1))
        rv20 = logret.rolling(20).std() * np.sqrt(252)
        frame["rv20"] = rv20.reindex(frame.index)
        if "unadjusted_close" in px.columns:
            frame["spot_unadj"] = pd.to_numeric(px["unadjusted_close"],
                                                errors="coerce").reindex(frame.index)
    else:
        frame["rv20"] = np.nan
    if "spot_unadj" not in frame.columns:
        frame["spot_unadj"] = frame["spot"]                     # no-split fallback

    # 3. derived dials (the pending-study instruments)
    frame["vrp_pts"] = (frame["iv45"] - frame["rv20"]) * 100          # Study 5
    frame["slope5_pts"] = (frame["iv45"] - frame["iv45"].shift(5)) * 100  # Study 2
    frame["term_pts"] = (frame["iv30"] - frame["iv90"]) * 100          # candidate #1
    frame["iv_rank"] = frame["iv45"].rolling(252, min_periods=60) \
        .apply(lambda w: (w.rank(pct=True).iloc[-1]), raw=False)       # Study 3 (IVR)
    return frame.dropna(subset=["iv45"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", default=STOCK_UNIVERSE)
    ap.add_argument("--start", default="2005-01-01", help="max-depth start (Lab 20yr)")
    ap.add_argument("--end", default="2026-07-21")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    syms = a.symbols or STOCK_UNIVERSE

    if a.dry_run:
        print(f"DRY RUN — would pull {len(syms)} names, {a.start}..{a.end}, "
              f"2 calls each (~{len(syms)*2*1.1:.0f}s at 1 req/s):")
        print("  ", ", ".join(syms))
        print(f"  IVX  {iv.EP_IVX}   +   stock {iv.EP_STOCK_EOD}")
        print(f"  -> {OUT_DIR}/<SYMBOL>.parquet")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for i, sym in enumerate(syms, 1):
        try:
            df = build(sym, a.start, a.end)
            path = os.path.join(OUT_DIR, f"{sym}.parquet")
            df.to_parquet(path)
            span = f"{df.index.min().date()}..{df.index.max().date()}"
            rows.append((sym, len(df), span, True))
            print(f"[{i:>2}/{len(syms)}] OK  {sym:<6} {len(df):>5} rows  {span}", flush=True)
        except Exception as e:
            rows.append((sym, 0, "", False))
            print(f"[{i:>2}/{len(syms)}] ERR {sym:<6} {e}", flush=True)

    ok = [r for r in rows if r[3]]
    print(f"\n================ STUDY 1 PULL ================")
    print(f"names ok       : {len(ok)}/{len(syms)}")
    print(f"total rows     : {sum(r[1] for r in rows):,}")
    if ok:
        earliest = min(r[2].split('..')[0] for r in ok)
        print(f"deepest history: back to {earliest}")
    print(f"stored under   : {OUT_DIR}/")
    print("\nUnblocks: Study 2 (slope5_pts), Study 5 (vrp_pts), Study 3 / crisis-peak "
          "(iv_rank), candidate #1 (term_pts). 16Δ IV is a phase-2 add (skew endpoint).")
    return 0 if len(ok) >= 0.8 * len(syms) else 1


if __name__ == "__main__":
    sys.exit(main())
