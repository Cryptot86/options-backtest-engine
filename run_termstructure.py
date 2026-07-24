#!/usr/bin/env python
"""Candidate #1 — Term-Structure Carry: 'sell the front when the curve is steep.'

Most-replicated options-return result in the literature (Vasquez JFQA; Johnson).
ENTRY (per name): term_pts (= iv30 − iv90) rolling-252d percentile <= 20th
(steep contango — near-term insurance overpaid) AND 5-day IV change <= 0.
One position per name (21-trading-day suppression). Two arms on the SAME entries:

  ARM A — naked 16Δ put, ~40 DTE, engine exits (50%/21DTE). The carry as a gate.
  ARM B — ATM PUT CALENDAR (short ~30d / long ~90d, same strike): isolates the
          carry itself. Exits: +25% of debit / −50% / front 10 DTE / slope
          percentile back above 50th (regime exit).

KILL BARS (pre-registered):
  A: >= +$60/tr AND top5 < 50% (benchmark: ungated class ~$24-53/tr; VIX gate $129)
  B: >= +$30/tr AND top5 < 50% AND ret-on-debit mean > 0
Pre-reg (research agent): contango is ~80% of days so the gate may barely
filter; the CALENDAR ARM DIES ON DOUBLE SPREADS. This run decides.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

from run_iv_backtest import price_one                    # arm A = same engine
from src.otbt.config import COST
from src.otbt.pricing import ivol_client as iv

IVDIR = os.path.join("data_cache", "iv_series", "stocks")
CAL_COSTS = 4 * (COST.commission_per_contract + COST.exchange_fees_per_contract) \
    + 4 * (COST.slippage_ticks * 100)


def signals_for(sym: str, d: pd.DataFrame) -> pd.DataFrame:
    pct = d.term_pts.rolling(252, min_periods=120).rank(pct=True)
    d = d.assign(term_pct=pct)
    hit = (pct <= 0.20) & (d.slope5_pts <= 0)
    rows, last = [], -99
    for i, flag in enumerate(hit.values):
        if flag and i - last > 21:
            rows.append(dict(symbol=sym, date=d.index[i]))
            last = i
    return pd.DataFrame(rows), d["term_pct"]


def calendar_trade(sym, d, term_pct, entry):
    scol = "spot_unadj" if "spot_unadj" in d.columns else "spot"
    spot = float(d.loc[entry, scol])
    c = iv.list_contracts(sym, entry.strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=23)).strftime("%Y-%m-%d"),
                          (entry + pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
                          round(spot * 0.96, 2), round(spot * 1.04, 2), "P")
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = pd.to_numeric(c["strike"], errors="coerce")
    c["exp"] = pd.to_datetime(c["expirationdate"])
    c["dte"] = (c["exp"] - entry).dt.days
    fr = c[(c.dte >= 23) & (c.dte <= 45)]
    bk = c[(c.dte >= 70) & (c.dte <= 120)]
    if fr.empty or bk.empty:
        return None
    fexp = fr.loc[(fr.dte - 30).abs().idxmin(), "exp"]
    bexp = bk.loc[(bk.dte - 90).abs().idxmin(), "exp"]
    ks = set(fr[fr.exp == fexp].strike) & set(bk[bk.exp == bexp].strike)
    if not ks:
        return None
    K = min(ks, key=lambda k: abs(k - spot))
    rf = fr[(fr.exp == fexp) & (fr.strike == K)].iloc[0]
    rb = bk[(bk.exp == bexp) & (bk.strike == K)].iloc[0]
    end = (entry + pd.Timedelta(days=95)).strftime("%Y-%m-%d")
    pf = iv.contract_path(int(rf.optionid), entry.strftime("%Y-%m-%d"), end)
    pb = iv.contract_path(int(rb.optionid), entry.strftime("%Y-%m-%d"), end)
    if pf.empty or pb.empty or entry not in pf.index or entry not in pb.index:
        return None
    vf, vb = float(pf.loc[entry, "close"]), float(pb.loc[entry, "close"])
    debit = vb - vf
    if debit <= 0.05:
        return None
    days = d.index[d.index >= entry]
    worst = 0.0
    reason, exit_val, exit_dt = "front_10dte", None, days[-1]
    for dt in days[1:]:
        if dt in pf.index: vf = float(pf.loc[dt, "close"])
        if dt in pb.index: vb = float(pb.loc[dt, "close"])
        val = vb - vf
        worst = min(worst, (val - debit) * 100)
        fdte = (pd.Timestamp(fexp) - dt).days
        if val >= 1.25 * debit:
            reason, exit_val, exit_dt = "tp_25", 1.25 * debit, dt; break
        if val <= 0.50 * debit:
            reason, exit_val, exit_dt = "stop_50", 0.50 * debit, dt; break
        if dt in term_pct.index and term_pct.loc[dt] > 0.50:
            reason, exit_val, exit_dt = "slope_regime", val, dt; break
        if fdte <= 10:
            reason, exit_val, exit_dt = "front_10dte", val, dt; break
    if exit_val is None:
        exit_val = vb - vf
    pnl = (exit_val - debit) * 100 - CAL_COSTS
    return dict(symbol=sym, date=entry, strike=float(K), debit=round(debit, 2),
                pnl=round(pnl, 1), mae=round(worst, 1), exit_reason=reason,
                ret_pct=round(100 * pnl / (debit * 100), 2))


def pool(tag, s, datecol="date"):
    if not len(s):
        print(f"  {tag:<26} n=   0"); return
    eq = s.sort_values(datecol).pnl.cumsum()
    top5 = s.pnl.nlargest(5).sum()
    print(f"  {tag:<26} n={len(s):>4}  ${s.pnl.sum():>8.0f}  avg=${s.pnl.mean():>6.1f}  "
          f"win={100*(s.pnl>0).mean():>5.1f}%  worst=${s.pnl.min():>6.0f}  "
          f"worstMAE=${s.mae.min():>6.0f}  eqDD=${(eq.cummax()-eq).max():>7.0f}  "
          f"top5={100*top5/s.pnl.sum() if s.pnl.sum() else 0:>4.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    univ = a.symbols or [f[:-8] for f in sorted(os.listdir(IVDIR))
                         if f.endswith(".parquet") and f != "SPY.parquet"]
    frames, pcts, sigs = {}, {}, []
    for s in univ:
        frames[s] = pd.read_parquet(os.path.join(IVDIR, f"{s}.parquet"))
        sg, pc = signals_for(s, frames[s])
        pcts[s] = pc
        if len(sg):
            sigs.append(sg)
    sig = pd.concat(sigs, ignore_index=True)
    if a.limit:
        sig = sig.groupby("symbol").head(a.limit)
    print(f"term-structure entries (pctile<=20 & slope5<=0, 21td dedupe): {len(sig)}",
          flush=True)

    A, B = [], []
    for i, r in enumerate(sig.itertuples(), 1):
        try:
            ta = price_one(r.symbol, {"date": r.date}, frames[r.symbol])
            if ta:
                ta["date"] = r.date; ta["symbol"] = r.symbol; A.append(ta)
        except Exception:
            pass
        try:
            tb = calendar_trade(r.symbol, frames[r.symbol], pcts[r.symbol], r.date)
            if tb:
                B.append(tb)
        except Exception:
            pass
        if i % 200 == 0:
            print(f"  {i}/{len(sig)}  (A={len(A)} B={len(B)})", flush=True)

    dA, dB = pd.DataFrame(A), pd.DataFrame(B)
    dA.to_csv("reports/termstruct_armA_trades.csv", index=False)
    dB.to_csv("reports/termstruct_armB_trades.csv", index=False)
    print("\n===== ARM A — naked 16Δ put gated by term-structure =====")
    if len(dA):
        pool("all entries", dA)
    print("KILL BAR A: >= +$60/tr AND top5<50%  (VIX-gate benchmark $129/tr)")
    print("\n===== ARM B — ATM put calendar 30/90 (the carry itself) =====")
    if len(dB):
        pool("all entries", dB)
        print(f"  ret-on-debit mean {dB.ret_pct.mean():+.2f}%  median {dB.ret_pct.median():+.2f}%")
        print(f"  exit mix: {dB.exit_reason.value_counts().to_dict()}")
        print("\n  per-name (top/bottom 5 by $):")
        per = dB.groupby("symbol").pnl.agg(["count", "sum"]).sort_values("sum")
        print(pd.concat([per.head(5), per.tail(5)]).to_string())
    print("KILL BAR B: >= +$30/tr AND top5<50% AND ret-on-debit mean > 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
