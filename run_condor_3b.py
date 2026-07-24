#!/usr/bin/env python
"""Study 3b — earnings IRON CONDOR on the calm half (unlocked by 3a, 2026-07-23).

3a receipts: calm names' implied move 4.95% vs realized 2.52% — fear ~2x
overpriced on 78% of 507 events. This prices the actual harvest:
  ENTER at the last close BEFORE the announcement (peak fear),
  EXIT at the next close AFTER it (crush captured, gap taken).
  Legs: short ~16Δ put + short ~16Δ call, long ~5Δ wings. Front-month expiry
  just after the event. 8 contract-sides of costs.

KILL BAR (pre-registered): >= +$40/tr pooled after costs AND top-5 share < 50%
AND positive at EQUAL RISK (mean return-on-max-risk > 0). Pre-reg (manifest):
marginal-to-breakeven. Failure mode: the 22% of events where fear was RIGHT.

Usage: python run_condor_3b.py [--symbols ...] [--limit N]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from src.otbt.config import COST
from src.otbt.pricing import ivol_client as iv
from src.otbt.pricing.blackscholes import strike_for_delta
from src.otbt.pricing.ivol_client import _get

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
CALM = ["BAC", "COST", "CVX", "DIS", "GOOGL", "GS", "HD", "JNJ", "JPM", "LLY",
        "MCD", "MSFT", "PFE", "UNH", "WFC", "WMT", "XOM"]      # 3a's calm half
COSTS_RT = 8 * (COST.commission_per_contract + COST.exchange_fees_per_contract) \
    + 8 * (COST.slippage_ticks * 100)


def earnings_dates(sym, start="2019-01-01", end="2026-07-01"):
    df = _get("/equities/eod/history-earnings-calendar",
              {"symbols": sym, "from": start, "to": end})
    if df.empty:
        return df
    df["earning_date"] = pd.to_datetime(df["earning_date"])
    return df.sort_values("earning_date")


def condor_event(sym, d, ann, tod):
    idx = d.index
    A = pd.Timestamp(ann)
    before = idx[idx <= A] if str(tod).upper() != "BMO" else idx[idx < A]
    if len(before) < 2:
        return None
    e0 = before[-1]                                   # entry: last close pre-news
    after = idx[idx > e0]
    if not len(after):
        return None
    e1 = after[0]                                     # exit: first close post-news
    scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
    spot = float(d.loc[e0, scol]); ivv = float(d.loc[e0, "iv45"])
    T = 30 / 365.0
    kps = strike_for_delta(spot, T, ivv, 0.16, kind="put")
    kpl = strike_for_delta(spot, T, ivv, 0.05, kind="put")
    kcs = strike_for_delta(spot, T, ivv, 0.16, kind="call")
    kcl = strike_for_delta(spot, T, ivv, 0.05, kind="call")
    c = iv.list_contracts(sym, e0.strftime("%Y-%m-%d"),
                          e1.strftime("%Y-%m-%d"),
                          (e0 + pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
                          round(kpl * 0.85, 2), round(kcl * 1.15, 2))
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"])
    front = c[c.exp == c.exp.min()]
    def snap(right, k):
        e = front[front.callput.astype(str).str.upper().str[0] == right]
        if e.empty: return None
        return e.iloc[(e.strike - k).abs().argmin()]
    legs = {"ps": (snap("P", kps), -1), "pl": (snap("P", kpl), +1),
            "cs": (snap("C", kcs), -1), "cl": (snap("C", kcl), +1)}
    if any(v[0] is None for v in legs.values()):
        return None
    if legs["pl"][0].strike >= legs["ps"][0].strike or legs["cl"][0].strike <= legs["cs"][0].strike:
        return None
    e0s, e1s = e0.strftime("%Y-%m-%d"), e1.strftime("%Y-%m-%d")
    v0 = v1 = 0.0
    for tag, (row, sgn) in legs.items():
        p = iv.contract_path(int(row.optionid), e0s, e1s)
        if p.empty or e0 not in p.index:
            return None
        m1 = float(p.loc[e1, "close"]) if e1 in p.index else float(p.iloc[-1]["close"])
        v0 += -sgn * float(p.loc[e0, "close"])         # credit positive
        v1 += -sgn * m1
    if v0 <= 0.05:
        return None
    wp = legs["ps"][0].strike - legs["pl"][0].strike
    wc = legs["cl"][0].strike - legs["cs"][0].strike
    max_risk = (max(wp, wc) - v0) * 100
    pnl = (v0 - v1) * 100 - COSTS_RT
    return dict(symbol=sym, ann=A.date(), credit=round(v0, 2),
                max_risk=round(max_risk, 0), pnl=round(pnl, 1),
                ret_pct=round(100 * pnl / max_risk, 2) if max_risk > 0 else np.nan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=CALM)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rows = []
    for i, sym in enumerate(a.symbols, 1):
        d = pd.read_parquet(os.path.join(IVDIR, f"{sym}.parquet"))
        ev = earnings_dates(sym)
        if a.limit:
            ev = ev.head(a.limit)
        done = 0
        for _, e in ev.iterrows():
            try:
                t = condor_event(sym, d, e["earning_date"], e.get("time_of_day_code", "AMC"))
            except Exception:
                t = None
            if t:
                rows.append(t); done += 1
        print(f"[{i:>2}/{len(a.symbols)}] {sym:<6} events={len(ev):>3} priced={done}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("reports/condor_3b_trades.csv", index=False)
    if df.empty:
        print("nothing priced"); return 1
    top5 = df.pnl.nlargest(5).sum()
    norm = df.ret_pct / 100 * 2000                      # sized @$2K max-risk
    print(f"\n========== STUDY 3b — earnings iron condor (calm half) ==========")
    print(f"events: {len(df)}  win {100*(df.pnl>0).mean():.1f}%")
    print(f"raw    : total ${df.pnl.sum():,.0f}  avg ${df.pnl.mean():+.1f}/tr  worst ${df.pnl.min():.0f}  "
          f"top5 {100*top5/df.pnl.sum() if df.pnl.sum() else 0:.0f}%")
    print(f"equal-risk (@$2K): total ${norm.sum():,.0f}  avg ${norm.mean():+.1f}/tr  "
          f"mean ret-on-risk {df.ret_pct.mean():+.2f}%")
    print("\nper-name (raw $):")
    for s_, s in df.groupby("symbol"):
        print(f"  {s_:<6} n={len(s):>3}  ${s.pnl.sum():>7.0f}  avg=${s.pnl.mean():>6.1f}  win={100*(s.pnl>0).mean():>5.1f}%")
    print("\nKILL BAR: >= +$40/tr raw AND top5<50% AND equal-risk mean > 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
