#!/usr/bin/env python
"""EXIT-TYPE SHOOTOUT — TJ's 10x100 stock system, 5 majors, 10 years.

Entry (all variants): fresh 10>100 EMA golden cross, D+1 close basis.
Re-entry after a stop-out (all variants share it): close crosses back above the
10-EMA while 10>100 still holds (the 'remount').
Exit variants (death cross = regime exit in ALL variants):
  A cross-only          : exit ONLY on 10<100 death cross  (TJ's current law)
  B fixed 2xATR         : + stop at entry - 2*ATR14(entry), close-based
  C chandelier 3xATR    : + trail at highestClose(since entry) - 3*ATR14, close-based
  D -15% circuit breaker: + stop at entry*0.85, close-based
Sizing: equal $10K notional per entry (isolates the EXIT variable).
PRIOR (TJ's action book): no-stop/cross-only is best for 10x100. Test anyway.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd

SYMS = ["MSFT", "TSLA", "AAPL", "NVDA", "GOOGL"]
START = pd.Timestamp("2016-08-01"); END = pd.Timestamp("2026-08-01")
NOTIONAL = 10_000.0


def load(sym):
    df = pd.read_parquet(f"data_cache/{sym}.parquet")
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns=str.lower)
    df["e10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["e100"] = df["close"].ewm(span=100, adjust=False).mean()
    tr = pd.concat([(df.high - df.low),
                    (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["up"] = df.e10 > df.e100
    return df.loc[(df.index >= START - pd.Timedelta(days=200)) & (df.index <= END)]


def run(df, variant):
    trades = []
    in_pos = False; stopped_out = False
    entry_px = peak = atr0 = 0.0; entry_dt = None
    idx = df.index
    for i in range(1, len(df)):
        dt = idx[i]; r = df.iloc[i]; prev = df.iloc[i - 1]
        if dt < START:
            continue
        fresh_cross = r.up and not prev.up
        remount = stopped_out and r.up and r.close > r.e10 and prev.close <= prev.e10
        if not in_pos:
            if fresh_cross or remount:
                in_pos, stopped_out = True, False
                entry_px, peak, atr0, entry_dt = r.close, r.close, r.atr, dt
            continue
        peak = max(peak, r.close)
        exit_now, why = False, ""
        if not r.up:                                     # death cross — all variants
            exit_now, why = True, "cross"
        elif variant == "B" and r.close < entry_px - 2 * atr0:
            exit_now, why = True, "atr_stop"
        elif variant == "C" and r.close < peak - 3 * r.atr:
            exit_now, why = True, "chandelier"
        elif variant == "D" and r.close < entry_px * 0.85:
            exit_now, why = True, "breaker"
        if exit_now:
            sh = NOTIONAL / entry_px
            giveback = (peak - r.close) / (peak - entry_px) if peak > entry_px * 1.001 else 0.0
            trades.append(dict(entry=entry_dt, exit=dt, entry_px=entry_px, exit_px=r.close,
                               pnl=sh * (r.close - entry_px), ret=r.close / entry_px - 1,
                               giveback=giveback, why=why))
            in_pos = False
            stopped_out = why != "cross"
    if in_pos:                                           # mark open position (ARM case)
        r = df.iloc[-1]; sh = NOTIONAL / entry_px
        trades.append(dict(entry=entry_dt, exit=idx[-1], entry_px=entry_px, exit_px=r.close,
                           pnl=sh * (r.close - entry_px), ret=r.close / entry_px - 1,
                           giveback=(peak - r.close) / (peak - entry_px) if peak > entry_px * 1.001 else 0.0,
                           why="open"))
    return trades


VARIANTS = {"A": "cross-only (current law)", "B": "fixed 2xATR stop",
            "C": "chandelier 3xATR trail", "D": "-15% circuit breaker"}
all_rows = {}
for v in VARIANTS:
    rows = []
    for s in SYMS:
        for t in run(load(s), v):
            t["symbol"] = s; rows.append(t)
    all_rows[v] = pd.DataFrame(rows).sort_values("exit")

print(f"10x100 exit shootout — {', '.join(SYMS)} · {START.date()} → {END.date()} · $10K/position\n")
print(f"{'variant':<26}{'n':>4}{'total':>10}{'win%':>6}{'avg':>8}{'best':>9}{'worst':>8}"
      f"{'eqMaxDD':>9}{'tot/DD':>7}{'med giveback':>13}")
for v, name in VARIANTS.items():
    d = all_rows[v]; p = d.pnl
    eq = p.cumsum(); dd = (eq.cummax() - eq).max()
    winners = d[d.pnl > 0]
    print(f"{name:<26}{len(d):>4}{p.sum():>10,.0f}{100*(p>0).mean():>5.0f}%{p.mean():>8,.0f}"
          f"{p.max():>9,.0f}{p.min():>8,.0f}{dd:>9,.0f}{(p.sum()/dd if dd else np.inf):>7.2f}"
          f"{100*winners.giveback.median():>12.0f}%")
print("\nbiggest single winner per variant (the ARM question — does the stop choke the monster?):")
for v, name in VARIANTS.items():
    d = all_rows[v]; b = d.loc[d.pnl.idxmax()]
    print(f"  {name:<26} {b.symbol} {b.entry.date()}→{b.exit.date()}  +{100*b.ret:.0f}%  (${b.pnl:,.0f}, gave back {100*b.giveback:.0f}% of peak run)")
os.makedirs("reports", exist_ok=True)
pd.concat([all_rows[v].assign(variant=v) for v in VARIANTS]).to_csv("reports/stock_exit_shootout.csv", index=False)
print("\nwrote reports/stock_exit_shootout.csv")
