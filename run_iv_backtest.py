#!/usr/bin/env python
"""5-stock x 2-method backtest, IVol-sourced option marks -> $ / win% / max-DD.

Same engine, IVol data. Methods = the two confirmed put entries:
  bb_2sd        (2-SD dip in uptrend)     five_day_low  (new 5-day low in uptrend)

Per signal: generate on the price series -> select the 16-delta put at entry via
IVol (by delta+DTE; split-safe) -> pull its daily marks -> replay the engine's
50%/21DTE management -> trade P&L + MAE (max drawdown during the hold, close-based).

Reported per (stock, method): trades, total $, win%, avg $, worst trade,
worst MAE (deepest in-hold drawdown), and equity-curve max drawdown.

Usage:
  python run_iv_backtest.py                       # MSFT AAPL NVDA JPM XOM, both methods
  python run_iv_backtest.py --symbols MSFT --methods bb_2sd
  python run_iv_backtest.py --limit 20            # cap signals/name for a quick look
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

from src.otbt.config import COST, TRADE
from src.otbt.pricing.simulate_real import CONTRACT_MULT, _costs_per_side
from src.otbt.signals.engine import generate_signals
from src.otbt.pricing import ivol_client as iv

SLIP = COST.slippage_ticks * CONTRACT_MULT
METHODS = ["bb_2sd", "five_day_low"]
DEFAULT_SYMS = ["MSFT", "AAPL", "NVDA", "JPM", "XOM"]


def price_df(sym: str) -> pd.DataFrame:
    """Local OHLC for signal generation (same basis our validated system uses)."""
    df = pd.read_parquet(os.path.join("data_cache", f"{sym}.parquet"))
    df.index = pd.to_datetime(df.index)
    return df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]


def replay(path: pd.DataFrame, entry_px: float, expiration, strike: float,
           underlying_exit_spot=None) -> dict:
    """Engine management on IVol's daily marks (mirror of simulate_real:93-140).
    Returns pnl, mae (worst in-hold drawdown $), exit_reason, days_held."""
    tp = entry_px * (1 - TRADE.take_profit_pct)
    days = path.index
    last, worst = entry_px, 0.0
    exit_opt, reason, exit_dt = None, "expiration", days[-1]
    for dt in days[1:]:
        opt = float(path.loc[dt, "close"]) if dt in path.index else last
        last = opt
        worst = min(worst, (entry_px - opt) * CONTRACT_MULT)      # MAE during hold
        dte = (pd.Timestamp(expiration) - dt).days
        if opt <= tp:
            exit_opt, reason, exit_dt = tp, "take_profit_50", dt; break
        if dte <= TRADE.manage_dte:
            exit_opt, reason, exit_dt = opt, "manage_21dte", dt; break
    if exit_opt is None:
        exit_opt = max(strike - underlying_exit_spot, 0.0) if underlying_exit_spot else last
    pnl = entry_px * CONTRACT_MULT - exit_opt * CONTRACT_MULT - 2 * SLIP - _costs_per_side(2)
    return dict(pnl=pnl, mae=worst, exit_reason=reason,
                days_held=(pd.Timestamp(exit_dt) - days[0]).days)


def price_one(sym: str, sig, ivdf: pd.DataFrame) -> dict | None:
    """Select the 16-delta put at entry (real-IV strike estimate, unadjusted
    basis) and run it. Returns a trade dict or None."""
    entry = pd.Timestamp(sig["date"])
    if entry not in ivdf.index:
        return None
    spot = float(ivdf.loc[entry, "spot"])          # unadjusted (matches listed strikes)
    ivv = float(ivdf.loc[entry, "iv45"])
    sel = iv.select_16d_put(sym, entry.strftime("%Y-%m-%d"), spot, ivv,
                            dte_target=TRADE.dte_target,
                            dte_min=TRADE.dte_min, dte_max=TRADE.dte_max,
                            target_delta=TRADE.target_delta)
    if sel is None or sel.get("optionid") is None:
        return None
    end = (entry + pd.Timedelta(days=70)).strftime("%Y-%m-%d")
    path = iv.contract_path(sel["optionid"], entry.strftime("%Y-%m-%d"), end)
    if path.empty or entry not in path.index:
        return None
    entry_px = float(path.loc[entry, "close"])
    if entry_px <= 0:
        return None
    r = replay(path, entry_px, sel["expiration"], sel["strike"])
    r.update(symbol=sym, entry=entry.date(), strike=sel["strike"], entry_px=entry_px)
    return r


def summarize(name: str, trades: list[dict]) -> dict:
    if not trades:
        return dict(cell=name, n=0)
    df = pd.DataFrame(trades).sort_values("entry")
    pnl = df["pnl"]
    equity = pnl.cumsum()
    max_dd = float((equity.cummax() - equity).max())        # equity-curve drawdown
    return dict(
        cell=name, n=len(df),
        total=round(pnl.sum(), 0), avg=round(pnl.mean(), 1),
        win_pct=round(100 * (pnl > 0).mean(), 1),
        worst_trade=round(pnl.min(), 0),
        worst_mae=round(df["mae"].min(), 0),                # deepest in-hold drawdown
        equity_maxdd=round(max_dd, 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_SYMS)
    ap.add_argument("--methods", nargs="*", default=METHODS)
    ap.add_argument("--limit", type=int, default=0, help="cap signals/name (0=all)")
    a = ap.parse_args()

    prices = {s: price_df(s) for s in a.symbols}
    ivframes = {s: pd.read_parquet(os.path.join("data_cache", "iv_series", "stocks", f"{s}.parquet"))
                for s in a.symbols}
    ledger = generate_signals(prices, a.methods)
    ledger = ledger[ledger["iv_proxy"].notna()]
    print(f"signals: {len(ledger)} across {len(a.symbols)} names x {len(a.methods)} methods\n")

    rows = []
    for sym in a.symbols:
        for method in a.methods:
            sigs = ledger[(ledger.symbol == sym) & (ledger.signal_type == method)]
            if a.limit:
                sigs = sigs.iloc[:: max(1, len(sigs) // a.limit)]   # evenly spaced sample
            trades = []
            for _, sig in sigs.iterrows():
                try:
                    t = price_one(sym, sig, ivframes[sym])
                    if t:
                        trades.append(t)
                except Exception as e:
                    print(f"  [warn] {sym} {sig['date']}: {e}", flush=True)
            rows.append(summarize(f"{sym}/{method}", trades))
            r = rows[-1]
            print(f"{r['cell']:<20} n={r.get('n',0):>3}  "
                  + (f"${r['total']:>8.0f}  win={r['win_pct']:>5.1f}%  "
                     f"avg=${r['avg']:>6.1f}  worstMAE=${r['worst_mae']:>7.0f}  "
                     f"eqMaxDD=${r['equity_maxdd']:>7.0f}" if r.get('n') else "(no trades)"),
                  flush=True)

    out = pd.DataFrame(rows)
    out.to_csv("reports/iv_backtest_5x2.csv", index=False)
    print("\nwrote reports/iv_backtest_5x2.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
