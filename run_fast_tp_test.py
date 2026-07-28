#!/usr/bin/env python
"""Fast-TP test: does banking early (30/40%) beat the 50%/21DTE law on equities?

TJ's Q (2026): put at 30% profit in 1-2 days — take it, or hold to 50%? Re-prices
the VIX-gated stock book (cached option paths, $0) under TP = {30,40,50}% and
also asks the money question: the trades that hit 30% FAST — what did holding to
the 50% rule actually earn on them? Prior receipt: 'bank 40% if hit in 5 days'
cost the book -$26.8K vs flat-50. This checks 30% specifically.
"""
from __future__ import annotations
import os, numpy as np, pandas as pd
from src.otbt.config import COST
from src.otbt.pricing.simulate_real import CONTRACT_MULT, _costs_per_side
from src.otbt.signals.engine import generate_signals
from src.otbt.pricing import ivol_client as iv
from run_iv_backtest import price_df

SLIP = COST.slippage_ticks * CONTRACT_MULT
IVDIR = os.path.join("data_cache", "iv_series", "stocks")

def replay_tp(path, entry_px, tp_pct, expiration, strike):
    """Return (pnl, exit_day_index) for a given take-profit %."""
    tp_price = entry_px * (1 - tp_pct)
    days = path.index
    exit_opt, di = None, len(days) - 1
    for i, dt in enumerate(days[1:], 1):
        opt = float(path.loc[dt, "close"])
        dte = (pd.Timestamp(expiration) - dt).days
        if opt <= tp_price:
            exit_opt, di = tp_price, i; break
        if dte <= 21:
            exit_opt, di = opt, i; break
    if exit_opt is None:
        exit_opt = float(path.iloc[-1]["close"])
    pnl = entry_px*CONTRACT_MULT - exit_opt*CONTRACT_MULT - 2*SLIP - _costs_per_side(2)
    return pnl, di

def main():
    # gated stock trades already priced -> reuse their contracts from cache
    t = pd.read_csv("reports/iv_backtest_trades.csv"); t["entry"]=pd.to_datetime(t.entry)
    g = t[t.vix_gate==True].copy()
    syms = sorted(g.symbol.unique())
    ivf = {s: pd.read_parquet(os.path.join(IVDIR,f"{s}.parquet")) for s in syms}
    prices = {s: price_df(s) for s in syms}
    led = generate_signals(prices, ["bb_2sd","five_day_low"])
    led["date"]=pd.to_datetime(led.date)
    rows=[]
    for r in g.itertuples():
        sig = led[(led.symbol==r.symbol)&(led.date==r.entry)]
        if sig.empty: continue
        entry=r.entry
        d=ivf[r.symbol]
        if entry not in d.index: continue
        col="spot_unadj" if "spot_unadj" in d.columns else "spot"
        sel=iv.select_16d_put(r.symbol, entry.strftime("%Y-%m-%d"), float(d.loc[entry,col]),
                              float(d.loc[entry,"iv45"]))
        if not sel or sel.get("optionid") is None: continue
        end=(entry+pd.Timedelta(days=70)).strftime("%Y-%m-%d")
        path=iv.contract_path(sel["optionid"], entry.strftime("%Y-%m-%d"), end)
        if path.empty or entry not in path.index: continue
        epx=float(path.loc[entry,"close"])
        if epx<=0: continue
        rec={"symbol":r.symbol,"entry":entry}
        for tp in (0.30,0.40,0.50):
            pnl,di=replay_tp(path,epx,tp,sel["expiration"],sel["strike"])
            rec[f"pnl{int(tp*100)}"]=pnl; rec[f"day{int(tp*100)}"]=di
        rows.append(rec)
    df=pd.DataFrame(rows)
    if df.empty: print("nothing priced"); return
    print(f"gated equity trades re-priced: {len(df)}\n")
    print(f"{'TP rule':<14}{'total$':>10}{'avg/tr':>8}{'win%':>7}{'avg days':>10}")
    for tp in (30,40,50):
        p=df[f"pnl{tp}"]; dd=df[f"day{tp}"]
        print(f"exit @ {tp}%{'':<6}${p.sum():>9,.0f}{p.mean():>8.1f}{100*(p>0).mean():>6.0f}%{dd.mean():>9.1f}")
    # the money question: trades that hit 30% FAST (<=2 days) — held to 50% earned?
    fast = df[(df.day30<=2)]
    print(f"\nTrades that hit 30% within 2 days: {len(fast)}")
    print(f"  if banked at 30%: total ${fast.pnl30.sum():,.0f} (avg ${fast.pnl30.mean():.1f})")
    print(f"  if held to 50%/21DTE: total ${fast.pnl50.sum():,.0f} (avg ${fast.pnl50.mean():.1f})")
    print(f"  COST of banking those early: ${fast.pnl30.sum()-fast.pnl50.sum():,.0f}")
    df.to_csv("reports/fast_tp_test.csv",index=False)

if __name__=="__main__":
    main()
