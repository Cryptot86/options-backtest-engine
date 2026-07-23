#!/usr/bin/env python
"""TJ's scenario test: at the 21-DTE exit the trade is IN LOSS — what if we held?

For the CL call lines (sell rally in DOWNTREND): 'trend intact' = 10EMA < 100EMA
still true at the 21-DTE exit (thesis alive; the rally hurt the strike but did
not flip the regime). The backtest's only exits for bb_2sd_call were 50%TP and
21DTE — no trend exit — so trend state at exit must be MEASURED, not inferred.

Replays the CL call suite twice from the GLBX cache (OTBT_OFFLINE=1 -> $0):
  A) law as-is  : manage at 21 DTE
  B) hold-to-exp: manage_dte=0 (TP still active; no calendar exit)
then joins per-trade and reports, for the trades that were LOSING at 21 DTE:
  - split by trend state at the 21-DTE date (still down vs flipped up)
  - held-to-expiry P&L vs the 21-DTE exit P&L for each bucket.
"""
from __future__ import annotations

import os
os.environ["OTBT_OFFLINE"] = "1"          # cache-only: never spend a cent

import dataclasses

import pandas as pd

from src.otbt.config import TradeConfig
from src.otbt.signals.engine import generate_call_signals, _prep
from src.otbt.pricing.glbx_options import get_continuous, simulate_fut_trade

TRADE_LAW = TradeConfig()
TRADE_HOLD = dataclasses.replace(TRADE_LAW, manage_dte=0)


def run(trade_cfg, cont, prepped, ledger):
    out = []
    for _, sig in ledger.iterrows():
        try:
            r = simulate_fut_trade("CL", sig["date"], prepped, sig["signal_type"],
                                   float(sig["iv_proxy"]), kind="call",
                                   trade=trade_cfg)
        except Exception:
            r = None
        if r is not None:
            out.append(r.__dict__)
    return pd.DataFrame(out)


def main():
    cont = get_continuous("CL", "2012-01-01", "2025-06-30")
    prepped = _prep(cont)
    ledger = generate_call_signals({"CL": cont})
    ledger = ledger[ledger["iv_proxy"].notna()]
    # D+1 entry (run-28 basis)
    idx = cont.index
    def _shift(d):
        pos = idx.searchsorted(pd.Timestamp(d)) + 1
        return idx[pos] if pos < len(idx) else None
    ledger = ledger.assign(date=ledger["date"].map(_shift)).dropna(subset=["date"])
    print(f"signals: {len(ledger)} (cache-only replay x2)", flush=True)

    A = run(TRADE_LAW, cont, prepped, ledger)
    B = run(TRADE_HOLD, cont, prepped, ledger)
    print(f"priced: law={len(A)}  hold={len(B)}", flush=True)

    key = ["signal_type", "entry_date"]
    A["entry_date"] = pd.to_datetime(A["entry_date"])
    B["entry_date"] = pd.to_datetime(B["entry_date"])
    j = A.merge(B, on=key, suffixes=("_law", "_hold"))

    # the scenario: law-exit was manage_21dte AND in loss
    s = j[(j.exit_reason_law == "manage_21dte") & (j.pnl_law < 0)].copy()
    # trend state at the 21-DTE exit date (call line: intact = still DOWNtrend)
    ema = prepped[["ema10", "ema100"]] if "ema10" in prepped else None
    if ema is None:
        import src.otbt.signals.indicators as ind
        ema = pd.DataFrame({"ema10": ind.ema(cont["close"], 10),
                            "ema100": ind.ema(cont["close"], 100)})
    exit_dt = pd.to_datetime(s["exit_date_law"])
    state = ema.reindex(exit_dt, method="ffill")
    s["trend_still_down"] = (state["ema10"].values < state["ema100"].values)

    print(f"\n21-DTE exits in LOSS: {len(s)}")
    for label, sub in [("thesis ALIVE (still downtrend)", s[s.trend_still_down]),
                       ("thesis DEAD (trend flipped up)", s[~s.trend_still_down])]:
        if not len(sub):
            print(f"\n  {label}: n=0"); continue
        d = sub.pnl_hold - sub.pnl_law
        print(f"\n  {label}: n={len(sub)}")
        print(f"    exit at 21 DTE (law) : total ${sub.pnl_law.sum():>9.0f}  avg ${sub.pnl_law.mean():>7.0f}")
        print(f"    held to expiry       : total ${sub.pnl_hold.sum():>9.0f}  avg ${sub.pnl_hold.mean():>7.0f}")
        print(f"    holding changed P&L  : total ${d.sum():>9.0f}  avg ${d.mean():>7.0f}  "
              f"(improved {100*(d>0).mean():.0f}% of trades)")
        print(f"    extra pain while holding: worst extra MAE "
              f"${(sub.mae_hold - sub.mae_law).min():.0f}")
    s.to_csv("reports/cl_21dte_counterfactual.csv", index=False)
    print("\nwrote reports/cl_21dte_counterfactual.csv")


if __name__ == "__main__":
    main()
