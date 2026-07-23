#!/usr/bin/env python
"""Studies 7 & 3a — the earnings pair from the ivol-raid manifest.

STUDY 7 (pre-earnings vol-ramp, broad retest; TJ 2026-07-22):
  Buy front-month-ish ATM straddle ~10 trading days before earnings, sell at the
  last close before the announcement (AMC -> announce-day close; BMO -> prior
  close). FULL 35-stock universe, 2019-2026, $10K-notional normalization.
  KILL BAR (pre-set): >= +$40/tr pooled after costs; else the grave gets its
  second date. Pre-registered: dies again — the tail is arbed.

STUDY 3a (implied-move vs realized, calm-half names; censused 2026-07-17):
  Implied move = exit-day straddle value / spot (shares Study 7's pulls — $0
  extra). Realized move = |gap return| announcement close -> next close.
  If implied <= realized on the calm half, the condor (Study 3b, 4-leg) is dead
  without pricing a single condor. Pre-registered: marginal-to-breakeven.

Usage:
  python run_earnings_studies.py                  # full 35, 2019-2026
  python run_earnings_studies.py --symbols MSFT AAPL --start 2023-01-01
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from src.otbt.config import COST
from src.otbt.pricing import ivol_client as iv
from src.otbt.pricing.ivol_client import _get

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
            "CRM", "COST", "LLY", "UNH", "JNJ", "PFE", "JPM", "BAC", "WFC", "GS",
            "XOM", "CVX", "COP", "CAT", "DE", "BA", "HD", "MCD", "NKE", "DIS",
            "WMT", "C", "TSM", "PLTR", "COIN"]
# 2-leg round trip: 4 contract-sides commission+fees + 4 leg-sides slippage
COSTS_RT = 4 * (COST.commission_per_contract + COST.exchange_fees_per_contract) \
    + 4 * (COST.slippage_ticks * 100)


def earnings_dates(sym: str, start: str, end: str) -> pd.DataFrame:
    df = _get("/equities/eod/history-earnings-calendar",
              {"symbols": sym, "from": start, "to": end})
    if df.empty:
        return df
    df["earning_date"] = pd.to_datetime(df["earning_date"])
    return df.sort_values("earning_date")


def straddle_event(sym: str, ivdf: pd.DataFrame, ann, tod: str) -> dict | None:
    """Price one pre-earnings straddle: entry D-10, exit last close before the
    announcement. Returns the trade dict or None (missing data)."""
    idx = ivdf.index
    A = pd.Timestamp(ann)
    # last tradeable close BEFORE the announcement lands
    before = idx[idx <= A] if str(tod).upper() != "BMO" else idx[idx < A]
    if len(before) < 11:
        return None
    exit_day = before[-1]
    entry = before[-11]                       # ~10 trading days earlier
    spot_e = float(ivdf.loc[entry, "spot"])
    # front-month-ish: contracts listed at entry, expiring just after the event
    c = iv.list_contracts(sym, entry.strftime("%Y-%m-%d"),
                          exit_day.strftime("%Y-%m-%d"),
                          (exit_day + pd.Timedelta(days=45)).strftime("%Y-%m-%d"),
                          round(spot_e * 0.94, 2), round(spot_e * 1.06, 2))
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"])
    front = c[c["exp"] == c["exp"].min()]
    # ATM strike that has BOTH legs listed
    both = front.groupby("strike")["callput"].nunique()
    strikes = both[both == 2].index
    if not len(strikes):
        return None
    K = strikes[np.argmin(np.abs(strikes - spot_e))]
    legs = front[front["strike"] == K]
    marks_e, marks_x = 0.0, 0.0
    for _, leg in legs.iterrows():
        path = iv.contract_path(int(leg["optionid"]), entry.strftime("%Y-%m-%d"),
                                exit_day.strftime("%Y-%m-%d"))
        if path.empty or entry not in path.index or exit_day not in path.index:
            return None
        marks_e += float(path.loc[entry, "close"])
        marks_x += float(path.loc[exit_day, "close"])
    if marks_e <= 0:
        return None
    scale = 10_000.0 / (spot_e * 100)                       # $10K notional
    pnl = ((marks_x - marks_e) * 100 - COSTS_RT) * scale
    # study 3a: implied vs realized move around the announcement
    after = idx[idx > exit_day]
    spot_x = float(ivdf.loc[exit_day, "spot"])
    realized = abs(float(ivdf.loc[after[0], "spot"]) / spot_x - 1) if len(after) else np.nan
    return dict(symbol=sym, ann=A.date(), entry=entry.date(), exit=exit_day.date(),
                strike=float(K), debit=marks_e, exit_val=marks_x, pnl_10k=round(pnl, 1),
                impl_move=marks_x / spot_x, real_move=realized)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=UNIVERSE)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-01")
    a = ap.parse_args()

    trades, skipped = [], 0
    for i, sym in enumerate(a.symbols, 1):
        p = os.path.join(IVDIR, f"{sym}.parquet")
        if not os.path.exists(p):
            continue
        ivdf = pd.read_parquet(p)
        ev = earnings_dates(sym, a.start, a.end)
        done = 0
        for _, e in ev.iterrows():
            try:
                t = straddle_event(sym, ivdf, e["earning_date"],
                                   e.get("time_of_day_code", "AMC"))
            except Exception:
                t = None
            if t:
                trades.append(t); done += 1
            else:
                skipped += 1
        print(f"[{i:>2}/{len(a.symbols)}] {sym:<6} events={len(ev):>3} priced={done}",
              flush=True)

    df = pd.DataFrame(trades)
    df.to_csv("reports/earnings_studies.csv", index=False)
    if df.empty:
        print("no events priced"); return 1

    print(f"\n========== STUDY 7 — pre-earnings vol-ramp straddle ==========")
    print(f"events priced : {len(df)}  (skipped {skipped})")
    print(f"pooled        : ${df.pnl_10k.sum():,.0f}  avg ${df.pnl_10k.mean():+.1f}/tr "
          f"(per $10K notional)  win {100*(df.pnl_10k>0).mean():.1f}%")
    print(f"median        : ${df.pnl_10k.median():+.1f}   p5 ${df.pnl_10k.quantile(.05):.0f} "
          f"/ p95 ${df.pnl_10k.quantile(.95):.0f}")
    kill7 = df.pnl_10k.mean() >= 40
    print(f"KILL BAR >= +$40/tr: {'PASSES — write it up' if kill7 else 'FAILS — second date with the grave, as pre-registered'}")

    # calm half = bottom half of universe by median iv45 (deterministic, ex-ante rule)
    med_iv = {s: pd.read_parquet(os.path.join(IVDIR, f"{s}.parquet"))["iv45"].median()
              for s in a.symbols if os.path.exists(os.path.join(IVDIR, f"{s}.parquet"))}
    calm = sorted(med_iv, key=med_iv.get)[: len(med_iv) // 2]
    c3 = df[df.symbol.isin(calm)].dropna(subset=["real_move"])
    print(f"\n========== STUDY 3a — implied vs realized move (calm half) ==========")
    print(f"calm names    : {', '.join(sorted(calm))}")
    print(f"events        : {len(c3)}")
    print(f"implied move  : median {100*c3.impl_move.median():.2f}%   "
          f"realized gap: median {100*c3.real_move.median():.2f}%")
    edge = (c3.impl_move - c3.real_move)
    print(f"edge (impl-real): median {100*edge.median():+.2f} pts, "
          f"implied > realized on {100*(edge>0).mean():.0f}% of events")
    print("VERDICT: " + ("condor premise EXISTS -> Study 3b (4-leg) is justified"
                         if edge.median() > 0 else
                         "no premise on calm half -> condor grave, no 4-leg spend"))
    print("\nwrote reports/earnings_studies.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
