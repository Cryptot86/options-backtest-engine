#!/usr/bin/env python
"""STUDY: equity bb_2sd_call — sell 16Δ CALLs on stocks, exact MCL rule.

Signal: close >= upper 2-SD band while ema10 < ema100 (DOWNTREND). Entry D+1,
sell ~16Δ call ~40DTE (flexible), exit 50% credit or 21 DTE, no stops.

KILL BAR (pre-registered 2026-07-31, BEFORE any data):
  license-consideration ONLY if pooled >= +$60/tr AND worst trade >= -$3,500
  AND top-5 trades < 50% of profit AND not carried by one name. Else BURY.
Prior (stated): buried — equity call premium is structurally thin (skew) and
the upside tail is uncapped (squeeze/buyout). Receipts: copper calls toxic,
SI calls rejected; call selling survived only in ENERGY.

Usage: python run_equity_call_sell.py [--symbols A B C] [--limit N]
"""
from __future__ import annotations
import argparse, glob, os, sys
import numpy as np, pandas as pd

from src.otbt.config import COST, TRADE
from src.otbt.pricing.simulate_real import CONTRACT_MULT, _costs_per_side
from src.otbt.signals.engine import generate_call_signals
from src.otbt.pricing import ivol_client as iv

SLIP = COST.slippage_ticks * CONTRACT_MULT


def price_df(sym):
    df = pd.read_parquet(os.path.join("data_cache", f"{sym}.parquet"))
    df.index = pd.to_datetime(df.index)
    return df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]


def replay_call(path, entry_px, expiration, strike, exit_spot=None):
    """50%/21DTE management of a SHORT CALL on daily marks."""
    tp = entry_px * (1 - TRADE.take_profit_pct)
    days = path.index
    last, worst = entry_px, 0.0
    exit_opt, reason, exit_dt = None, "expiration", days[-1]
    for dt in days[1:]:
        opt = float(path.loc[dt, "close"]) if dt in path.index else last
        last = opt
        worst = min(worst, (entry_px - opt) * CONTRACT_MULT)
        dte = (pd.Timestamp(expiration) - dt).days
        if opt <= tp:
            exit_opt, reason, exit_dt = tp, "take_profit_50", dt; break
        if dte <= TRADE.manage_dte:
            exit_opt, reason, exit_dt = opt, "manage_21dte", dt; break
    if exit_opt is None:
        exit_opt = max(exit_spot - strike, 0.0) if exit_spot else last   # CALL intrinsic
    pnl = entry_px * CONTRACT_MULT - exit_opt * CONTRACT_MULT - 2 * SLIP - _costs_per_side(2)
    return dict(pnl=pnl, mae=worst, exit_reason=reason,
                days_held=(pd.Timestamp(exit_dt) - days[0]).days)


def price_one(sym, sig, ivdf):
    entry = pd.Timestamp(sig["date"])
    if entry not in ivdf.index:
        return None
    col = "spot_unadj" if "spot_unadj" in ivdf.columns else "spot"
    spot = float(ivdf.loc[entry, col]); ivv = float(ivdf.loc[entry, "iv45"])
    sel = iv.select_16d_call(sym, entry.strftime("%Y-%m-%d"), spot, ivv,
                             dte_target=TRADE.dte_target, dte_min=TRADE.dte_min,
                             dte_max=TRADE.dte_max, target_delta=TRADE.target_delta)
    if sel is None or sel.get("optionid") is None:
        return None
    end = (entry + pd.Timedelta(days=70)).strftime("%Y-%m-%d")
    path = iv.contract_path(sel["optionid"], entry.strftime("%Y-%m-%d"), end)
    if path.empty or entry not in path.index:
        return None
    entry_px = float(path.loc[entry, "close"])
    if entry_px <= 0:
        return None
    r = replay_call(path, entry_px, sel["expiration"], sel["strike"])
    r.update(symbol=sym, entry=entry.date(), strike=sel["strike"], entry_px=entry_px,
             iv_rank=float(ivdf.loc[entry, "iv_rank"]),
             slope5=float(ivdf.loc[entry, "slope5_pts"]),
             vrp=float(ivdf.loc[entry, "vrp_pts"]))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    syms = a.symbols or sorted(os.path.basename(p).replace(".parquet", "")
                               for p in glob.glob("data_cache/iv_series/stocks/*.parquet")
                               if "SPY" not in p)
    syms = [s for s in syms if os.path.exists(f"data_cache/{s}.parquet")]
    prices = {s: price_df(s) for s in syms}
    ledger = generate_call_signals(prices)
    ledger = ledger[ledger.signal_type == "bb_2sd_call"]
    print(f"bb_2sd_call signals: {len(ledger)} across {len(syms)} names", flush=True)

    all_trades = []
    for sym in syms:
        ivdf = pd.read_parquet(f"data_cache/iv_series/stocks/{sym}.parquet")
        sigs = ledger[ledger.symbol == sym]
        if a.limit:
            sigs = sigs.iloc[:: max(1, len(sigs) // a.limit)]
        trades = []
        for _, sig in sigs.iterrows():
            try:
                t = price_one(sym, sig, ivdf)
                if t:
                    trades.append(t)
            except Exception as e:
                print(f"  [warn] {sym} {sig['date']}: {e}", flush=True)
        all_trades.extend(trades)
        if trades:
            p = pd.DataFrame(trades).pnl
            print(f"{sym:<6} n={len(trades):>3} total ${p.sum():>8,.0f} avg ${p.mean():>6.0f} "
                  f"win {100*(p>0).mean():>3.0f}% worst ${p.min():>7,.0f}", flush=True)
        else:
            print(f"{sym:<6} n=  0", flush=True)

    df = pd.DataFrame(all_trades)
    df.to_csv("reports/equity_call_sell_trades.csv", index=False)
    p = df.pnl
    top5 = p.nlargest(5).sum()
    print("\n===== POOLED (equity bb_2sd_call, 16Δ, 50%/21DTE) =====")
    print(f"n={len(df)}  total ${p.sum():,.0f}  avg ${p.mean():.1f}/tr  win {100*(p>0).mean():.1f}%")
    print(f"worst trade ${p.min():,.0f}  worst MAE ${df.mae.min():,.0f}  "
          f"top-5 share of profit: {100*top5/p.sum() if p.sum()>0 else float('nan'):.0f}%")
    by = df.groupby("symbol").pnl.agg(["count", "sum", "mean"]).sort_values("sum")
    print("\nworst names:\n", by.head(5).to_string())
    print("\nbest names:\n", by.tail(5).to_string())
    print("\nKILL BAR: >= +$60/tr AND worst >= -$3,500 AND top5 < 50% AND not one-name-carried")
    return 0


if __name__ == "__main__":
    sys.exit(main())
