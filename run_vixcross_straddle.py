#!/usr/bin/env python
"""Study 8 — TJ's hypothesis (2026-07-24): trend-following ON VOL ITSELF.

When the vol index turns UP on the 10x100 EMA model (10 EMA crosses above
100 EMA = vol regime shifting), BUY an ATM straddle (1 contract) on each of the
top-5 stocks. Exits = the validated Sleeve-3 straddle law: +50% / -40% / 21 DTE.

Vol series: SPY 30d IVX (the VIX clone we own for 13yr; CBOE VIX cache only
covers 2024+). Fresh crosses only. Straddle: ATM at spot_unadj, expiry nearest
40 DTE (30-55 window), both legs real marks.

KILL BAR (pre-registered): pooled >= +$40/tr after costs AND top-5 share < 50%
AND equal-risk (return-on-debit) mean > 0. Honest prior: uncertain — vol
momentum is real in the literature, but a 10x100 cross confirms LATE (vol has
already run); whipsaw crosses bleed double theta. The test decides.

Usage: python run_vixcross_straddle.py [--symbols ...] [--limit N]
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from src.otbt.config import COST
from src.otbt.pricing import ivol_client as iv

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
TOP5 = ["TSLA", "NFLX", "META", "NVDA", "LLY"]     # TJ's spec (top-5 by gated P&L)
COSTS_RT = 4 * (COST.commission_per_contract + COST.exchange_fees_per_contract) \
    + 4 * (COST.slippage_ticks * 100)              # 2 legs x 2 sides


def vix_cross_dates() -> pd.DatetimeIndex:
    spy = pd.read_parquet(os.path.join(IVDIR, "SPY.parquet"))
    v = spy["iv30"]
    e10, e100 = v.ewm(span=10).mean(), v.ewm(span=100).mean()
    up = e10 > e100
    fresh = up & ~up.shift(1, fill_value=False)
    return spy.index[fresh]


def straddle_trade(sym: str, d: pd.DataFrame, entry: pd.Timestamp) -> dict | None:
    if entry not in d.index:
        pos = d.index.searchsorted(entry)
        if pos >= len(d.index):
            return None
        entry = d.index[pos]
    scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
    spot = float(d.loc[entry, scol])
    c = iv.list_contracts(sym, entry.strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=55)).strftime("%Y-%m-%d"),
                          round(spot * 0.94, 2), round(spot * 1.06, 2))
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"])
    c["dte"] = (c["exp"] - entry).dt.days
    exp = c.loc[(c.dte - 40).abs().idxmin(), "exp"]
    e = c[c.exp == exp]
    both = e.groupby("strike")["callput"].nunique()
    ks = both[both == 2].index
    if not len(ks):
        return None
    K = ks[abs(ks - spot).argmin()]
    legs = e[e.strike == K]
    end = (entry + pd.Timedelta(days=80)).strftime("%Y-%m-%d")
    paths = []
    for _, leg in legs.iterrows():
        p = iv.contract_path(int(leg.optionid), entry.strftime("%Y-%m-%d"), end)
        if p.empty or entry not in p.index:
            return None
        paths.append(p["close"])
    debit = float(paths[0].loc[entry] + paths[1].loc[entry])
    if debit <= 0.1:
        return None
    days = d.index[d.index >= entry]
    v0, v1 = float(paths[0].loc[entry]), float(paths[1].loc[entry])
    worst = 0.0
    exit_reason, exit_val, exit_dt = "manage_21dte", None, days[-1]
    for dt in days[1:]:
        if dt in paths[0].index: v0 = float(paths[0].loc[dt])
        if dt in paths[1].index: v1 = float(paths[1].loc[dt])
        val = v0 + v1
        pnl_now = (val - debit) * 100
        worst = min(worst, pnl_now)
        dte = (pd.Timestamp(exp) - dt).days
        if val >= 1.5 * debit:
            exit_reason, exit_val, exit_dt = "tp_plus50", 1.5 * debit, dt; break
        if val <= 0.6 * debit:
            exit_reason, exit_val, exit_dt = "stop_minus40", 0.6 * debit, dt; break
        if dte <= 21:
            exit_reason, exit_val, exit_dt = "manage_21dte", val, dt; break
    if exit_val is None:
        exit_val = v0 + v1
    pnl = (exit_val - debit) * 100 - COSTS_RT
    return dict(symbol=sym, entry=entry.date(), strike=float(K), debit=round(debit, 2),
                pnl=round(pnl, 1), mae=round(worst, 1), exit_reason=exit_reason,
                ret_pct=round(100 * pnl / (debit * 100), 2),
                days_held=(pd.Timestamp(exit_dt) - entry).days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=TOP5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    crosses = vix_cross_dates()
    crosses = crosses[crosses >= "2013-06-01"]         # let the 100-EMA warm up
    if a.limit:
        crosses = crosses[:a.limit]
    print(f"VIX-clone 10x100 UP-crosses: {len(crosses)} "
          f"({crosses.min().date()} -> {crosses.max().date()})", flush=True)
    rows = []
    for sym in a.symbols:
        d = pd.read_parquet(os.path.join(IVDIR, f"{sym}.parquet"))
        done = 0
        for dt in crosses:
            try:
                t = straddle_trade(sym, d, dt)
            except Exception:
                t = None
            if t:
                rows.append(t); done += 1
        print(f"  {sym:<6} priced {done}/{len(crosses)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("reports/vixcross_straddle_trades.csv", index=False)
    if df.empty:
        print("nothing priced"); return 1
    top5 = df.pnl.nlargest(5).sum()
    print(f"\n========== STUDY 8 — VIX 10x100 up-cross -> buy straddle ==========")
    print(f"trades: {len(df)}  win {100*(df.pnl>0).mean():.1f}%")
    print(f"raw    : total ${df.pnl.sum():,.0f}  avg ${df.pnl.mean():+.1f}/tr  worst ${df.pnl.min():.0f}  "
          f"top5 {100*top5/df.pnl.sum() if df.pnl.sum() else 0:.0f}%")
    print(f"equal-risk: mean return-on-debit {df.ret_pct.mean():+.2f}%  median {df.ret_pct.median():+.2f}%")
    print(f"exit mix: {df.exit_reason.value_counts().to_dict()}")
    print("\nper-name:")
    for s_, s in df.groupby("symbol"):
        print(f"  {s_:<6} n={len(s):>3}  ${s.pnl.sum():>7.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>5.1f}%  worstMAE=${s.mae.min():>6.0f}")
    print("\nKILL BAR: >= +$40/tr raw AND top5<50% AND ret-on-debit mean > 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
