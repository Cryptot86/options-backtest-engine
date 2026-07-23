#!/usr/bin/env python
"""Study 5 — TJ's VRP-gap indicator: forecasted IV vs realized vol as an ENTRY.

Signal: vrp_pts (= iv45 − rv20, in vol points) CROSSES >= threshold {5,10,15}
(first bar of a cluster, like every other detector). Structure fixed: sell 16Δ
put, 50%/21DTE, same engine + costs as every other line.

Price each unique (name, entry-date) ONCE (union over thresholds); every
threshold × variant line is then a FILTER on the same priced table:
  alone | +trend (10>100) | +lights (iv_rank>=.5 & slope5<=0) | +earnings-safe
  (no announcement within the ~45d hold window)

KILL BAR (pre-set, manifest): >= +$60/tr AND worst >= -$1,500 AND materially
non-overlapping with existing lines (share of entries within ±3d of a bb_2sd /
five_day_low entry). Benchmark: name-gate clean +$108/tr.
Pre-registered: gap-alone fails the tail; gap+lights collapses into the gate.
Concentration check (top-5 share) prints before any verdict.

Usage:
  python run_vrp_gap.py                    # full universe
  python run_vrp_gap.py --symbols MSFT --limit 5   # smoke
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from run_iv_backtest import price_one                      # same engine pipe
from src.otbt.pricing.ivol_client import _get

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
            "CRM", "COST", "LLY", "UNH", "JNJ", "PFE", "JPM", "BAC", "WFC", "GS",
            "XOM", "CVX", "COP", "CAT", "DE", "BA", "HD", "MCD", "NKE", "DIS",
            "WMT", "C", "TSM", "PLTR", "COIN"]
THRESHOLDS = (5, 10, 15)


def signals_for(sym: str, ivdf: pd.DataFrame) -> pd.DataFrame:
    ema10 = ivdf.spot.ewm(span=10).mean()
    ema100 = ivdf.spot.ewm(span=100).mean()
    rows = []
    for th in THRESHOLDS:
        hit = ivdf.vrp_pts >= th
        entry = hit & ~hit.shift(1, fill_value=False)
        for dt in ivdf.index[entry]:
            rows.append(dict(symbol=sym, date=dt, threshold=th,
                             trend_up=bool(ema10.loc[dt] > ema100.loc[dt]),
                             lights=bool(ivdf.loc[dt, "iv_rank"] >= 0.5
                                         and ivdf.loc[dt, "slope5_pts"] <= 0)))
    return pd.DataFrame(rows)


def earnings_dates(sym: str) -> pd.DatetimeIndex:
    df = _get("/equities/eod/history-earnings-calendar",
              {"symbols": sym, "from": "2013-01-01", "to": "2026-07-21"})
    if df.empty or "earning_date" not in df:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(df["earning_date"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=UNIVERSE)
    ap.add_argument("--limit", type=int, default=0, help="cap unique entries/name (smoke)")
    a = ap.parse_args()

    # 1. signals (local, free)
    sigs, ivframes, earn = [], {}, {}
    for s in a.symbols:
        p = os.path.join(IVDIR, f"{s}.parquet")
        if not os.path.exists(p):
            continue
        ivframes[s] = pd.read_parquet(p)
        sigs.append(signals_for(s, ivframes[s]))
        earn[s] = earnings_dates(s)
    sig = pd.concat(sigs, ignore_index=True)
    uniq = sig.drop_duplicates(["symbol", "date"]).copy()
    if a.limit:
        uniq = uniq.groupby("symbol").head(a.limit)
    print(f"signals: {len(sig)} (thresholds pooled) -> unique entries to price: {len(uniq)}",
          flush=True)

    # 2. price each unique entry once (same engine as every other line)
    priced = []
    for i, (_, srow) in enumerate(uniq.iterrows(), 1):
        try:
            t = price_one(srow.symbol, {"date": srow.date}, ivframes[srow.symbol])
        except Exception:
            t = None
        if t:
            t["date"] = srow.date
            priced.append(t)
        if i % 250 == 0:
            print(f"  priced {i}/{len(uniq)} ({len(priced)} ok)", flush=True)
    tdf = pd.DataFrame(priced)
    if tdf.empty:
        print("nothing priced"); return 1
    tdf["date"] = pd.to_datetime(tdf["date"])
    # earnings-safe flag: no announcement within 45 calendar days of entry
    tdf["earn_safe"] = [
        not ((earn.get(r.symbol, pd.DatetimeIndex([])) > r.date)
             & (earn.get(r.symbol, pd.DatetimeIndex([])) <= r.date + pd.Timedelta(days=45))).any()
        for r in tdf.itertuples()]
    full = sig.merge(tdf, on=["symbol", "date"], how="inner")
    full.to_csv("reports/vrp_gap_trades.csv", index=False)

    # 3. overlap vs existing lines (±3 trading-ish days, same symbol)
    overlap_pct = float("nan")
    try:
        ex = pd.read_csv("reports/iv_backtest_trades.csv")
        ex["entry"] = pd.to_datetime(ex["entry"])
        near = 0
        for r in tdf.itertuples():
            e = ex[ex.symbol == r.symbol]
            if len(e) and (abs(e.entry - r.date).min() <= pd.Timedelta(days=3)):
                near += 1
        overlap_pct = 100 * near / len(tdf)
    except Exception:
        pass

    def pool(tag, s):
        if not len(s):
            print(f"  {tag:<28} n=   0"); return None
        eq = s.sort_values("date").pnl.cumsum()
        top5 = s.pnl.nlargest(5).sum()
        print(f"  {tag:<28} n={len(s):>4}  ${s.pnl.sum():>8.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>5.1f}%  worst=${s.pnl.min():>6.0f}  "
              f"worstMAE=${s.mae.min():>6.0f}  eqDD=${(eq.cummax()-eq).max():>7.0f}  "
              f"top5={100*top5/s.pnl.sum() if s.pnl.sum() else 0:>4.0f}%")
        return s

    print(f"\noverlap with existing lines (±3d): {overlap_pct:.0f}% of entries")
    best = None
    for th in THRESHOLDS:
        m = full[full.threshold == th]
        print(f"\n===== gap >= {th} pts =====")
        pool("alone", m)
        pool("+trend", m[m.trend_up])
        pool("+lights", m[m.lights])
        pool("+earnings-safe", m[m.earn_safe])
        pool("+trend & lights & earn-safe", m[m.trend_up & m.lights & m.earn_safe])

    print("\n===== per-stock, gap>=10 +trend (the headline spec) =====")
    hs = full[(full.threshold == 10) & full.trend_up]
    for sym_, s in hs.groupby("symbol"):
        eq = s.sort_values("date").pnl.cumsum()
        print(f"  {sym_:<6} n={len(s):>3}  ${s.pnl.sum():>7.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>5.1f}%  worstMAE=${s.mae.min():>6.0f}")
    print("\nKILL BAR: >= +$60/tr AND worst >= -$1,500 AND non-overlapping. "
          "Benchmark: name-gate clean +$108/tr. Read top5% before believing any line.")
    print("wrote reports/vrp_gap_trades.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
