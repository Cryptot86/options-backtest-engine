#!/usr/bin/env python
"""Candidate #3 — Crisis-Peak Fade: the untested cell of the gate map.

Thesis (Stein/Poteshman/'Fading Fear'): the biggest harvestable VRP is the
post-panic overshoot — sell AFTER the spike has confirmed a peak, never into it.

ENTRY (per name): iv_rank hit >= 0.90 within the last 10 sessions AND iv45 has
closed lower k consecutive days (k in {2,3,5} — the confirmation IS the trade).
One position per name (21-trading-day suppression).
STRUCTURE: DEFINED RISK ONLY — short ~25Δ put / long ~5Δ put credit spread,
~45 DTE, strikes estimated from real iv45 on spot_unadj, snapped to listed.
EXITS: 50% of net credit | 21 DTE | HARD STOP if iv_rank makes a new high above
the trigger peak (the echo-wave defense). NO rolling.

KILL BAR (pre-registered before this run):
  pooled >= +$30/tr after costs (4 contract-sides) AND top-5 concentration
  < 50% AND n >= 100 for the judged variant. Failure mode on record: echo
  waves — RV stays elevated 30-90d post-spike and the spread bleeds.

Usage: python run_crisis_fade.py [--symbols ...] [--limit N]
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from src.otbt.config import COST
from src.otbt.pricing import ivol_client as iv
from src.otbt.pricing.blackscholes import strike_for_delta

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
COSTS_RT = 4 * (COST.commission_per_contract + COST.exchange_fees_per_contract) \
    + 4 * (COST.slippage_ticks * 100)          # 2 legs x 2 sides


def signals_for(sym: str, d: pd.DataFrame) -> pd.DataFrame:
    peak10 = d.iv_rank.rolling(10).max()
    down = d.iv45.diff() < 0
    run = down.groupby((~down).cumsum()).cumsum()
    rows = []
    for k in (2, 3, 5):
        sig = (peak10 >= 0.90) & (run == k)
        last = -99
        for i, flag in enumerate(sig.values):
            if flag and i - last > 21:
                rows.append(dict(symbol=sym, date=d.index[i], k=k,
                                 trigger_peak=float(peak10.iloc[i])))
                last = i
    return pd.DataFrame(rows)


def price_spread(sym: str, d: pd.DataFrame, entry: pd.Timestamp,
                 trigger_peak: float) -> dict | None:
    scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
    spot = float(d.loc[entry, scol]); ivv = float(d.loc[entry, "iv45"])
    T = 45 / 365.0
    ks = strike_for_delta(spot, T, ivv, 0.25, kind="put")   # short leg
    kl = strike_for_delta(spot, T, ivv, 0.05, kind="put")   # long wing
    c = iv.list_contracts(sym, entry.strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=35)).strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
                          round(kl * 0.85, 2), round(ks * 1.15, 2), "P")
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"])
    c["dte"] = (c["exp"] - entry).dt.days
    exp = c.loc[(c.dte - 45).abs().idxmin(), "exp"]
    e = c[c.exp == exp]
    row_s = e.iloc[(e.strike - ks).abs().argmin()]
    row_l = e.iloc[(e.strike - kl).abs().argmin()]
    if row_l.strike >= row_s.strike:
        return None
    end = (entry + pd.Timedelta(days=75)).strftime("%Y-%m-%d")
    ps = iv.contract_path(int(row_s.optionid), entry.strftime("%Y-%m-%d"), end)
    pl = iv.contract_path(int(row_l.optionid), entry.strftime("%Y-%m-%d"), end)
    if ps.empty or pl.empty or entry not in ps.index or entry not in pl.index:
        return None
    credit = float(ps.loc[entry, "close"]) - float(pl.loc[entry, "close"])
    if credit <= 0.05:
        return None
    days = d.index[(d.index >= entry)]
    vs, vl = float(ps.loc[entry, "close"]), float(pl.loc[entry, "close"])
    worst = 0.0
    exit_reason, exit_dt, exit_val = "expiration", None, None
    for dt in days[1:]:
        if dt > pd.Timestamp(exp):
            break
        if dt in ps.index: vs = float(ps.loc[dt, "close"])
        if dt in pl.index: vl = float(pl.loc[dt, "close"])
        v = vs - vl
        pnl_now = (credit - v) * 100
        worst = min(worst, pnl_now)
        dte = (pd.Timestamp(exp) - dt).days
        if v <= 0.5 * credit:
            exit_reason, exit_dt, exit_val = "take_profit_50", dt, 0.5 * credit; break
        if float(d.loc[dt, "iv_rank"]) > trigger_peak:
            exit_reason, exit_dt, exit_val = "rank_newhigh_stop", dt, v; break
        if dte <= 21:
            exit_reason, exit_dt, exit_val = "manage_21dte", dt, v; break
    if exit_val is None:                                    # expiry intrinsic
        last_day = days[days <= pd.Timestamp(exp)]
        Sx = float(d.loc[last_day[-1], scol]) if len(last_day) else spot
        exit_val = max(row_s.strike - Sx, 0) - max(row_l.strike - Sx, 0)
        exit_dt = last_day[-1] if len(last_day) else entry
    pnl = (credit - exit_val) * 100 - COSTS_RT
    return dict(symbol=sym, date=entry, credit=round(credit, 2),
                width=float(row_s.strike - row_l.strike), pnl=round(pnl, 1),
                mae=round(worst, 1), exit_reason=exit_reason,
                days_held=(pd.Timestamp(exit_dt) - entry).days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    univ = a.symbols or [f[:-8] for f in sorted(os.listdir(IVDIR))
                         if f.endswith(".parquet") and f != "SPY.parquet"]
    frames = {s: pd.read_parquet(os.path.join(IVDIR, f"{s}.parquet")) for s in univ}
    sig = pd.concat([signals_for(s, frames[s]) for s in univ], ignore_index=True)
    uniq = sig.drop_duplicates(["symbol", "date"]).copy()
    if a.limit:
        uniq = uniq.groupby("symbol").head(a.limit)
    print(f"signals {len(sig)} -> unique entries {len(uniq)}", flush=True)

    priced = []
    for i, r in enumerate(uniq.itertuples(), 1):
        try:
            t = price_spread(r.symbol, frames[r.symbol], r.date, r.trigger_peak)
        except Exception:
            t = None
        if t:
            priced.append(t)
        if i % 250 == 0:
            print(f"  priced {i}/{len(uniq)} ({len(priced)} ok)", flush=True)
    tdf = pd.DataFrame(priced)
    if tdf.empty:
        print("nothing priced"); return 1
    full = sig.merge(tdf, on=["symbol", "date"], how="inner")
    full.to_csv("reports/crisis_fade_trades.csv", index=False)

    def pool(tag, s):
        if not len(s):
            print(f"  {tag:<16} n=   0"); return
        eq = s.sort_values("date").pnl.cumsum()
        top5 = s.pnl.nlargest(5).sum()
        print(f"  {tag:<16} n={len(s):>4}  ${s.pnl.sum():>8.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>5.1f}%  worst=${s.pnl.min():>6.0f}  "
              f"worstMAE=${s.mae.min():>6.0f}  eqDD=${(eq.cummax()-eq).max():>7.0f}  "
              f"top5={100*top5/s.pnl.sum() if s.pnl.sum() else 0:>4.0f}%")

    print("\n===== crisis-peak fade — 25Δ/5Δ put credit spread, 45 DTE =====")
    for k in (2, 3, 5):
        pool(f"confirm k={k}", full[full.k == k])
    print("\n  exit reasons (k=3):")
    print(full[full.k == 3].exit_reason.value_counts().to_string())
    print("\n===== per-stock, k=3 =====")
    for sym_, s in full[full.k == 3].groupby("symbol"):
        print(f"  {sym_:<6} n={len(s):>3}  ${s.pnl.sum():>7.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>5.1f}%  worstMAE=${s.mae.min():>6.0f}")
    print("\nKILL BAR: >= +$30/tr AND top5 < 50% AND n >= 100. wrote reports/crisis_fade_trades.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
