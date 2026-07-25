#!/usr/bin/env python
"""Study 4 — (a) straddle tenor sweep + (b) bull-put-spread wing pricing.

4a: Sleeve-3 entry (name vol CHEAP: iv_rank<=0.30 & iv45<rv20, 21td dedupe) on
    5 mega-liquid names; buy ATM straddle at THREE tenors {30,45,60}d per entry;
    validated exits +50%/-40%/21DTE. DECISION (not kill): which tenor wins
    $/tr and ret-on-debit — incumbent is ~40d (validated line).
    Pre-reg: incumbent band holds; 30d dies on theta cliff, 60d too slow.

4b: The name-gate population's naked 16Δ puts are ALREADY priced (clean table).
    Price the 5Δ WING for each -> bull put spread P&L = naked + wing leg - costs.
    BPR: naked = RegT max(20%*spot - OTM, 10%*K)*100 + credit; spread = width*100
    - net credit. KILL BAR (manifest): spread per-BPR efficiency >= 3x naked AND
    per-trade >= $50. Pre-registered: licensed only as capacity variant.
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

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
A_NAMES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
TENORS = (30, 45, 60)
SIDE = COST.commission_per_contract + COST.exchange_fees_per_contract
SLIP = COST.slippage_ticks * 100


def straddle_at_tenor(sym, d, entry, tenor):
    scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
    spot = float(d.loc[entry, scol])
    c = iv.list_contracts(sym, entry.strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=tenor - 12)).strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=tenor + 15)).strftime("%Y-%m-%d"),
                          round(spot * 0.95, 2), round(spot * 1.05, 2))
    if c.empty:
        return None
    c = c.copy(); c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"]); c["dte"] = (c["exp"] - entry).dt.days
    exp = c.loc[(c.dte - tenor).abs().idxmin(), "exp"]
    e = c[c.exp == exp]
    both = e.groupby("strike")["callput"].nunique()
    ks = both[both == 2].index
    if not len(ks):
        return None
    K = ks[abs(ks - spot).argmin()]
    legs = e[e.strike == K]
    end = (entry + pd.Timedelta(days=tenor + 25)).strftime("%Y-%m-%d")
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
    reason, ev, mae = "tenor_21dte", None, 0.0
    for dt in days[1:]:
        if dt in paths[0].index: v0 = float(paths[0].loc[dt])
        if dt in paths[1].index: v1 = float(paths[1].loc[dt])
        val = v0 + v1
        mae = min(mae, (val - debit) * 100)
        if val >= 1.5 * debit:
            reason, ev = "tp_50", 1.5 * debit; break
        if val <= 0.6 * debit:
            reason, ev = "stop_40", 0.6 * debit; break
        if (pd.Timestamp(exp) - dt).days <= 21:
            reason, ev = "tenor_21dte", val; break
    if ev is None:
        ev = v0 + v1
    pnl = (ev - debit) * 100 - (4 * SIDE + 4 * SLIP)
    return dict(symbol=sym, date=entry, tenor=tenor, debit=round(debit, 2),
                pnl=round(pnl, 1), mae=round(mae, 1),
                ret_pct=round(100 * pnl / (debit * 100), 2), exit=reason)


def run_4a(limit=0):
    rows = []
    for sym in A_NAMES:
        d = pd.read_parquet(os.path.join(IVDIR, f"{sym}.parquet"))
        cheap = (d.iv_rank <= 0.30) & (d.iv45 < d.rv20)
        ent, last = [], -99
        for i, f in enumerate(cheap.values):
            if f and i - last > 21:
                ent.append(d.index[i]); last = i
        if limit:
            ent = ent[:limit]
        done = 0
        for e in ent:
            for tn in TENORS:
                try:
                    t = straddle_at_tenor(sym, d, e, tn)
                except Exception:
                    t = None
                if t:
                    rows.append(t); done += 1
        print(f"  4a {sym}: entries={len(ent)} legs priced={done}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("reports/study4a_straddle_tenors.csv", index=False)
    print("\n===== 4a — straddle tenor sweep (cheap-vol entries, +50/-40/21DTE) =====")
    for tn in TENORS:
        s = df[df.tenor == tn]
        if not len(s):
            continue
        top5 = s.pnl.nlargest(5).sum()
        print(f"  {tn}d: n={len(s):>3}  ${s.pnl.sum():>8.0f}  avg=${s.pnl.mean():>6.1f}  "
              f"win={100*(s.pnl>0).mean():>4.0f}%  ret-on-debit {s.ret_pct.mean():+5.1f}%  "
              f"worstMAE=${s.mae.min():>6.0f}  top5={100*top5/s.pnl.sum() if s.pnl.sum() else 0:.0f}%")
    print("  DECISION: incumbent ~45d must be beaten on BOTH $/tr and ret-on-debit to move.")


def run_4b(limit=0):
    t = pd.read_csv("reports/iv_backtest_trades.csv")
    t["entry"] = pd.to_datetime(t.entry)
    ng = t[t.name_gate == True].copy()
    if limit:
        ng = ng.groupby("symbol").head(limit)
    print(f"\n4b: name-gate naked puts already priced: {len(ng)} — pricing 5Δ wings",
          flush=True)
    frames = {s: pd.read_parquet(os.path.join(IVDIR, f"{s}.parquet"))
              for s in ng.symbol.unique()}
    rows = []
    for i, r in enumerate(ng.itertuples(), 1):
        d = frames[r.symbol]
        if r.entry not in d.index:
            continue
        scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
        spot = float(d.loc[r.entry, scol]); ivv = float(d.loc[r.entry, "iv45"])
        try:
            kw = strike_for_delta(spot, 40 / 365.0, ivv, 0.05, kind="put")
            c = iv.list_contracts(r.symbol, r.entry.strftime("%Y-%m-%d"),
                                  (r.entry + pd.Timedelta(days=25)).strftime("%Y-%m-%d"),
                                  (r.entry + pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
                                  round(kw * 0.75, 2), round(min(kw * 1.25, r.strike * 0.99), 2), "P")
            if c.empty:
                continue
            c = c.copy(); c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
            c["exp"] = pd.to_datetime(c["expirationdate"])
            c["dte"] = (c["exp"] - r.entry).dt.days
            c = c[(c.dte >= 25) & (c.dte <= 60) & (c.strike < r.strike)]
            if c.empty:
                continue
            row = c.iloc[((c.strike - kw).abs() + (c.dte - 40).abs() * 0.01).argmin()]
            end = (r.entry + pd.Timedelta(days=int(r.days_held) + 5)).strftime("%Y-%m-%d")
            p = iv.contract_path(int(row.optionid), r.entry.strftime("%Y-%m-%d"), end)
            if p.empty or r.entry not in p.index:
                continue
            wd = float(p.loc[r.entry, "close"])                     # wing debit
            wx = float(p["close"].iloc[-1])                          # at naked's exit
            wing_pnl = (wx - wd) * 100 - (2 * SIDE + 2 * SLIP)
            spread_pnl = r.pnl + wing_pnl
            width = r.strike - float(row.strike)
            net_credit = (r.entry_px - wd)
            bpr_naked = max(0.20 * spot - max(spot - r.strike, 0), 0.10 * r.strike) * 100 \
                + r.entry_px * 100
            bpr_spread = width * 100 - net_credit * 100
            rows.append(dict(symbol=r.symbol, entry=r.entry.date(), naked_pnl=r.pnl,
                             spread_pnl=round(spread_pnl, 1), wing_cost=round(wd * 100, 0),
                             bpr_naked=round(bpr_naked, 0), bpr_spread=round(bpr_spread, 0)))
        except Exception:
            pass
        if i % 100 == 0:
            print(f"  4b {i}/{len(ng)} ({len(rows)} ok)", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("reports/study4b_bps_trades.csv", index=False)
    if df.empty:
        print("4b: nothing priced"); return
    en = 100 * df.naked_pnl.sum() / df.bpr_naked.sum()
    es = 100 * df.spread_pnl.sum() / df.bpr_spread.sum()
    print(f"\n===== 4b — bull put spread vs naked (name-gate population) =====")
    print(f"  n={len(df)}  naked: ${df.naked_pnl.mean():+.1f}/tr on avg BPR ${df.bpr_naked.mean():,.0f} "
          f"-> {en:+.2f}% per-$BPR")
    print(f"          spread: ${df.spread_pnl.mean():+.1f}/tr on avg BPR ${df.bpr_spread.mean():,.0f} "
          f"-> {es:+.2f}% per-$BPR")
    print(f"  efficiency ratio (spread/naked per-BPR): {es/en if en else float('nan'):.2f}x   "
          f"wing avg cost ${df.wing_cost.mean():.0f}")
    print(f"  KILL BAR: ratio >= 3x AND spread per-trade >= $50 "
          f"(observed ${df.spread_pnl.mean():+.1f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["a", "b", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.part in ("b", "both"):
        run_4b(a.limit)
    if a.part in ("a", "both"):
        run_4a(a.limit)
    sys.exit(0)
