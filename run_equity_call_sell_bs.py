#!/usr/bin/env python
"""STUDY: equity bb_2sd_call (SELL CALL, exact MCL rule) — BS marks on REAL IV.

IVol sub is cancelled -> no vendor call marks. Method: mark-to-model BS priced
off each name's OWN daily iv45 + spot_unadj (13yr real series on disk).
KNOWN BIAS, favors the strategy: iv45 ~ ATM; equity call skew means real 16Δ
calls trade BELOW ATM vol, so the modeled credit is OVERSTATED. If the study
fails under a favorable bias, the burial is extra safe; if it passes, vendor
marks would be required before any license.

Rule (same as MCL): close >= upper 2-SD band while ema10<ema100 -> D+1 sell
16Δ call 40DTE -> exit 50% credit or 21 DTE -> else expiry intrinsic.

KILL BAR (pre-registered 2026-07-31): license-consideration only if pooled
>= +$60/tr AND worst trade >= -$3,500 AND top-5 < 50% of profit AND not
one-name-carried. Stated prior: BURIED.
"""
from __future__ import annotations
import glob, os, sys
import numpy as np, pandas as pd

from src.otbt.config import COST, TRADE
from src.otbt.pricing.simulate_real import CONTRACT_MULT, _costs_per_side
from src.otbt.pricing.blackscholes import bs_price, strike_for_delta
from src.otbt.signals.engine import generate_call_signals

SLIP = COST.slippage_ticks * CONTRACT_MULT
DTE = 40


def price_df(sym):
    df = pd.read_parquet(os.path.join("data_cache", f"{sym}.parquet"))
    df.index = pd.to_datetime(df.index)
    return df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]


def run_trade(ivdf, entry):
    """Sell 16Δ call at D+1 close basis; daily BS re-mark; 50%/21DTE/expiry."""
    if entry not in ivdf.index:
        return None
    scol = "spot_unadj" if "spot_unadj" in ivdf.columns else "spot"
    spot0 = float(ivdf.loc[entry, scol]); iv0 = float(ivdf.loc[entry, "iv45"])
    if not (spot0 > 0 and iv0 > 0):
        return None
    K = strike_for_delta(spot0, DTE / 365.0, iv0, 0.16, kind="call")
    credit = bs_price(spot0, K, DTE / 365.0, iv0, kind="call")
    if credit <= 0.01:
        return None
    expiry = entry + pd.Timedelta(days=DTE)
    tp = credit * (1 - TRADE.take_profit_pct)
    path = ivdf.loc[(ivdf.index > entry) & (ivdf.index <= expiry)]
    worst = 0.0; exit_px, reason, exit_dt = None, "expiration", expiry
    for dt, row in path.iterrows():
        T = max((expiry - dt).days, 0) / 365.0
        s, v = float(row[scol]), float(row["iv45"])
        opt = bs_price(s, K, T, v if v > 0 else iv0, kind="call") if T > 0 \
            else max(s - K, 0.0)
        worst = min(worst, (credit - opt) * CONTRACT_MULT)
        if opt <= tp:
            exit_px, reason, exit_dt = tp, "take_profit_50", dt; break
        if (expiry - dt).days <= TRADE.manage_dte:
            exit_px, reason, exit_dt = opt, "manage_21dte", dt; break
    if exit_px is None:
        s_last = float(path[scol].iloc[-1]) if len(path) else spot0
        exit_px = max(s_last - K, 0.0)
    pnl = (credit - exit_px) * CONTRACT_MULT - 2 * SLIP - _costs_per_side(2)
    return dict(entry=entry.date(), strike=round(K, 2), credit=round(credit, 2),
                pnl=pnl, mae=worst, exit_reason=reason,
                days_held=(pd.Timestamp(exit_dt) - entry).days)


def main():
    syms = sorted(os.path.basename(p).replace(".parquet", "")
                  for p in glob.glob("data_cache/iv_series/stocks/*.parquet") if "SPY" not in p)
    syms = [s for s in syms if os.path.exists(f"data_cache/{s}.parquet")]
    prices = {s: price_df(s) for s in syms}
    ledger = generate_call_signals(prices)
    ledger = ledger[ledger.signal_type == "bb_2sd_call"]
    print(f"bb_2sd_call signals: {len(ledger)} across {len(syms)} names", flush=True)

    all_trades = []
    for sym in syms:
        ivdf = pd.read_parquet(f"data_cache/iv_series/stocks/{sym}.parquet")
        ivdf.index = pd.to_datetime(ivdf.index)
        trades = []
        for _, sig in ledger[ledger.symbol == sym].iterrows():
            d = pd.Timestamp(sig["date"])
            nxt = ivdf.index[ivdf.index > d]              # D+1 discipline
            if len(nxt) == 0:
                continue
            t = run_trade(ivdf, nxt[0])
            if t:
                t["symbol"] = sym; trades.append(t)
        all_trades.extend(trades)
        if trades:
            p = pd.DataFrame(trades).pnl
            print(f"{sym:<6} n={len(trades):>3} total ${p.sum():>9,.0f} avg ${p.mean():>6.0f} "
                  f"win {100*(p>0).mean():>3.0f}% worst ${p.min():>8,.0f}", flush=True)

    df = pd.DataFrame(all_trades)
    df.to_csv("reports/equity_call_sell_bs_trades.csv", index=False)
    p = df.pnl
    prof = p.sum(); top5 = p.nlargest(5).sum()
    print("\n===== POOLED: equity bb_2sd_call (BS marks on real IV, bias FAVORS strategy) =====")
    print(f"n={len(df)}  total ${prof:,.0f}  avg ${p.mean():.1f}/tr  win {100*(p>0).mean():.1f}%")
    print(f"worst trade ${p.min():,.0f}   worst MAE ${df.mae.min():,.0f}   "
          f"top-5 share {100*top5/prof if prof>0 else float('nan'):.0f}%")
    by = df.groupby("symbol").pnl.agg(["count", "sum", "mean"]).sort_values("sum")
    print("\nworst 5 names:\n" + by.head(5).to_string())
    print("\nbest 5 names:\n" + by.tail(5).to_string())
    bar = (p.mean() >= 60) and (p.min() >= -3500) and (prof > 0 and top5 / prof < 0.5)
    print(f"\nKILL BAR (>=+$60/tr, worst>=-$3,500, top5<50%): {'PASSES — needs vendor-mark confirm' if bar else 'FAILS -> BURY'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
