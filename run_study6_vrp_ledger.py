#!/usr/bin/env python
"""Study 6 — VRP harvested per line (bookkeeping; $0, all local).

For every licensed line's historical trades: implied vol AT ENTRY minus the
realized vol that FOLLOWED over the ~21-trading-day hold. Positive = the line
truly harvests the variance risk premium; ~zero/negative = the P&L came from
direction/timing, not premium (still fine — but we should KNOW which engine
each line runs on). The manifest's question: "is MES true VRP? measured, not
assumed."

Sources (all cached): equity trades reports/iv_backtest_trades.csv + IV series;
futures trades db/results.sqlite (D+1 runs) + futures IV series + GLBX closes.
"""
from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd

H = 21   # trading-day hold horizon

def fwd_rv(close: pd.Series, h: int = H) -> pd.Series:
    lr = np.log(close / close.shift(1))
    f = lr.shift(-1).rolling(h).std() * np.sqrt(252)
    return f.shift(-(h - 1))

def line(tag, iv_at, rv_after, pnl=None):
    d = pd.DataFrame({"iv": iv_at, "rv": rv_after}).dropna()
    vrp = (d.iv - d.rv) * 100
    corr = ""
    if pnl is not None:
        p = pd.Series(pnl).reindex(d.index)
        if p.notna().sum() > 10:
            corr = f"  pnl~vrp corr {p.corr(vrp):+.2f}"
    print(f"  {tag:<34} n={len(d):>4}  VRP mean {vrp.mean():+6.2f} pts  "
          f"median {vrp.median():+6.2f}  positive {100*(vrp>0).mean():>3.0f}%{corr}")
    return vrp.mean()

print("========== STUDY 6 — VRP harvested per line ==========\n")
print("EQUITY lines (iv45 at entry vs realized-after, clean 35-name table):")
t = pd.read_csv("reports/iv_backtest_trades.csv"); t["entry"] = pd.to_datetime(t.entry)
IVD = "data_cache/iv_series/stocks"
ivf = {s: pd.read_parquet(os.path.join(IVD, f"{s}.parquet")) for s in t.symbol.unique()}
for s, f in ivf.items():
    f["rv_fwd"] = fwd_rv(f["spot"])
def look(row, col):
    f = ivf[row.symbol]
    return float(f.loc[row.entry, col]) if row.entry in f.index else np.nan
t["iv_at"] = [look(r, "iv45") for r in t.itertuples()]
t["rv_after"] = [look(r, "rv_fwd") for r in t.itertuples()]
for tag, m in [("stocks 5DL ungated", (t.method == "five_day_low")),
               ("stocks 5DL VIX-gated", (t.method == "five_day_low") & t.vix_gate),
               ("stocks bb_2sd ungated", (t.method == "bb_2sd")),
               ("stocks bb_2sd either-gate", (t.method == "bb_2sd") & (t.vix_gate | t.name_gate))]:
    s = t[m]
    line(tag, s.iv_at, s.rv_after, s.pnl)

print("\nFUTURES lines (line IV series at entry vs realized-after):")
con = sqlite3.connect("db/results.sqlite")
runs = {"ES puts (D+1, run 66)": (66, "ES", ["five_day_low", "bb_2sd"]),
        "GC bb_2sd puts (run 30)": (30, "GC", ["bb_2sd"]),
        "CL bb_2sd_call (run 28)": (28, "CL", ["bb_2sd_call"]),
        "NG bb_2sd_call (run 27)": (27, "NG", ["bb_2sd_call"])}
for tag, (rid, root, sigs) in runs.items():
    tr = pd.read_sql(f"SELECT symbol,signal_type,entry_date,pnl FROM trades "
                     f"WHERE run_id={rid} AND symbol='{root}'", con)
    tr = tr[tr.signal_type.isin(sigs)]
    tr["entry_date"] = pd.to_datetime(tr.entry_date)
    ivs = pd.read_parquet(f"data_cache/iv_series/{root}.parquet")
    if "date" in ivs.columns:
        ivs = ivs.set_index("date")
    ivs.index = pd.to_datetime(ivs.index)
    cont = pd.read_parquet(
        f"data_cache/databento/glbx/cont/{root}__2012-01-01__2026-06-30.parquet"
    ).set_index("date")["close"]
    rvf = fwd_rv(cont)
    iv_at = tr.entry_date.map(lambda d: float(ivs.loc[d, "iv"]) if d in ivs.index else np.nan)
    rv_after = tr.entry_date.map(lambda d: float(rvf.loc[d]) if d in rvf.index else np.nan)
    line(tag, iv_at.values, rv_after.values, tr.pnl.values)
con.close()
print("""
READ: positive mean = the line sells vol for more than what then happens =
TRUE VRP harvest. ~0/negative = the line's P&L is direction/timing (spot went
the right way), not premium. pnl~vrp corr > 0 = trade profits track the premium
capture. NQ/MNQ: no futures IV series built (Databento spend) — noted, not run.
MES = ES/10: the ES row answers the manifest's MES question.""")
