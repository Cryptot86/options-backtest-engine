#!/usr/bin/env python
"""THETA-CAP sim — does 'aggregate daily theta <= 3% of equity' change the book?

Rule under test: at any point, the sum of DAILY THETA (time-decay income $/day)
across all OPEN SHORT positions must stay <= THETA_CAP * equity. A new sell
signal that would push daily theta over the cap is skipped (skip_reason='theta').
Long options (straddles / long calls) PAY theta -> not counted as collection.

Data caveat: our trade store has no entry credit/theta. We PROXY it (generous,
upper-bound, so the cap is not understated):
  equity 16d put : credit ~= 2% of strike*100 ; theta = credit / DTE(=40)
  futures micros : fixed credit per contract   ; theta = credit / DTE(=40)
Live app should replace the proxy with the real chain theta at fill.
Runs the SAME full book (all sleeves + size-steps + cluster caps + dedupe) with
the theta cap OFF vs ON, and reports equity-curve impact + max daily theta seen.
"""
from __future__ import annotations
import os, sqlite3, numpy as np, pandas as pd

EQ0, START, END = 50_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
IVDIR = "data_cache/iv_series/stocks"
RF = 0.02 / 252
DTE = 40.0                       # avg entry DTE for theta proxy
CREDIT_EQ_FRAC = 0.02           # equity 16d put credit ~= 2% of strike notional (generous)
CREDIT_FUT = {"MES": 150.0, "MCL": 100.0, "MNG": 80.0, "MGC": 120.0}  # $/contract (generous)

# line: cluster, tail_anchor, base_margin, cap  (same as run_full_book.py)
LINE = {"EQ": ("EQIDX", 4520, 1200, 1), "MES": ("EQIDX", 1569, 1300, 2),
        "MCL": ("ENERGY", 290, 350, 5), "MNG": ("ENERGY", 200, 280, 5),
        "MGC": ("METALS", 823, 220, 2)}
BASECAP = {"ENERGY": 0.05, "METALS": 0.05, "EQIDX": 0.07}


def qty(tag, equity):
    _, anc, _, cap = LINE[tag]
    return int(np.clip(np.floor(0.02 * equity / anc), 1, cap))


def theta_of(tag, strike, contracts):
    """Daily theta ($/day) collected by a SHORT position (proxy)."""
    if tag == "EQ":
        credit = CREDIT_EQ_FRAC * strike * 100.0
    else:
        credit = CREDIT_FUT.get(tag, 100.0)
    return (credit / DTE) * contracts


# ---- assemble the full book (sell + buy sleeves) ----
trades = []
eq = pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"] = pd.to_datetime(eq.entry)
eq = eq[(eq.vix_gate == True) | (eq.name_gate == True)].drop_duplicates(["symbol", "entry"])
for r in eq.itertuples():
    trades.append(dict(d=r.entry, x=r.entry + pd.Timedelta(days=int(r.days_held)), pnl1=r.pnl,
                       tag="EQ", cluster="EQIDX", margin=1200, strike=r.strike,
                       name=f"EQ:{r.symbol}", book="sell"))
con = sqlite3.connect("db/results.sqlite")
for rid, tag, sigs in [(66, "MES", ["bb_2sd", "five_day_low"]), (28, "MCL", ["bb_2sd_call"]),
                       (27, "MNG", ["bb_2sd_call"]), (30, "MGC", ["bb_2sd"])]:
    cl, anc, mg, cap = LINE[tag]
    t = pd.read_sql(f"SELECT entry_date,pnl,days_held FROM trades WHERE run_id={rid} "
                    f"AND signal_type IN ({','.join(repr(s) for s in sigs)})", con)
    if t.empty:
        continue
    t["entry_date"] = pd.to_datetime(t.entry_date)
    for r in t.itertuples():
        trades.append(dict(d=r.entry_date, x=r.entry_date + pd.Timedelta(days=int(r.days_held)),
                           pnl1=r.pnl / 10.0, tag=tag, cluster=cl, margin=mg, strike=0.0,
                           name=tag, book="sell"))
# BUY book (theta payers, not counted toward collection, but part of the curve)
for rid in [71, 84, 96, 90, 91, 100, 101, 102, 103, 105]:
    t = pd.read_sql(f"SELECT entry_date,pnl FROM trades WHERE run_id={rid} AND signal_type='straddle_cheap'", con)
    if t.empty:
        continue
    fut = rid in (71, 84, 96)
    for r in t.itertuples():
        e = pd.to_datetime(r.entry_date)
        trades.append(dict(d=e, x=e + pd.Timedelta(days=21), pnl1=(r.pnl / 10.0 if fut else r.pnl),
                           tag="STRAD", cluster="LONGVOL", margin=1500, strike=0.0,
                           name=f"STRAD{rid}", book="buy"))
lc = pd.read_sql("SELECT entry_date,pnl FROM trades WHERE run_id=33 AND symbol IN ('ES','GC')", con)
for r in lc.itertuples():
    e = pd.to_datetime(r.entry_date)
    trades.append(dict(d=e, x=e + pd.Timedelta(days=30), pnl1=r.pnl / 10.0, tag="LCALL",
                       cluster="LONGCALL", margin=500, strike=0.0, name="LCALL", book="buy"))
con.close()
T = pd.DataFrame([x for x in trades if x["d"] >= START]).sort_values("d").reset_index(drop=True)
print(f"full book trades {START.date()}..: {len(T)}  ({T.tag.value_counts().to_dict()})\n")


def run(theta_cap=None):
    CAP = dict(BASECAP)
    equity, openp, taken, skip_theta, skip_other = EQ0, [], 0, 0, 0
    curve = {}; max_theta_pct = 0.0
    Tby = {d: g for d, g in T.groupby("d")}
    for day in pd.date_range(START, END, freq="D"):
        for p in [p for p in openp if p["x"] <= day]:
            equity += p["realpnl"]; openp.remove(p)
        deployed = sum(p["m"] for p in openp)
        equity += max(equity - deployed, 0) * RF
        # current aggregate daily theta from open SHORT positions
        cur_theta = sum(p["theta"] for p in openp if p["book"] == "sell")
        max_theta_pct = max(max_theta_pct, cur_theta / equity)
        names = {p["name"] for p in openp}; eqday = 0
        usedS = sum(p["m"] for p in openp if p["book"] == "sell")
        usedB = sum(p["m"] for p in openp if p["book"] == "buy")
        capS, capB = 0.50 * equity, 0.15 * equity
        if day in Tby:
            for _, r in Tby[day].iterrows():
                q = qty(r.tag, equity) if r.tag in LINE else 1
                mgn = r.margin * q; ok = True
                th = theta_of(r.tag, r.strike, q) if r.book == "sell" else 0.0
                if r["name"] in names: ok = False
                if r.tag == "EQ" and eqday >= 2: ok = False
                cap_, used = (capS, usedS) if r.book == "sell" else (capB, usedB)
                if used + mgn > cap_: ok = False
                if r.cluster in CAP:
                    ct = sum(p["tail"] for p in openp if p["cluster"] == r.cluster)
                    tanc = LINE[r.tag][1] if r.tag in LINE else mgn
                    if ct + tanc * q > CAP[r.cluster] * equity: ok = False
                tot = sum(p["tail"] for p in openp)
                if r.tag in LINE and tot + LINE[r.tag][1] * q > 0.12 * equity: ok = False
                # THETA CAP (only applies to sell book)
                theta_blocked = False
                if theta_cap is not None and r.book == "sell":
                    if cur_theta + th > theta_cap * equity:
                        ok = False; theta_blocked = True
                if ok:
                    tanc = LINE[r.tag][1] * q if r.tag in LINE else 0
                    openp.append(dict(name=r["name"], x=r.x, realpnl=r.pnl1 * q, m=mgn,
                                      tail=tanc, book=r.book, cluster=r.cluster, theta=th))
                    taken += 1
                    if r.book == "sell": usedS += mgn; cur_theta += th
                    else: usedB += mgn
                    names.add(r["name"])
                    if r.tag == "EQ": eqday += 1
                elif theta_blocked: skip_theta += 1
                else: skip_other += 1
        curve[day] = equity
    for p in openp: equity += p["realpnl"]
    cv = pd.Series(curve); yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    dd = ((cv.cummax() - cv) / cv.cummax()).max()
    cagr = (equity / EQ0) ** (1 / yrs) - 1
    return dict(final=equity, cagr=cagr, mddp=dd, mar=cagr / dd if dd else 0,
                taken=taken, skip_theta=skip_theta, skip_other=skip_other,
                max_theta_pct=max_theta_pct, curve=cv)


print(f"{'profile':<28}{'final$':>11}{'CAGR':>7}{'maxDD%':>8}{'MAR':>6}{'taken':>7}{'skipΘ':>7}{'maxΘ/eq':>9}")
for name, cap in [("NO theta cap", None), ("0.10% theta cap", 0.0010),
                  ("0.05% theta cap", 0.0005), ("0.03% theta cap (TJ)", 0.0003),
                  ("0.02% theta cap", 0.0002), ("0.01% theta cap", 0.0001)]:
    r = run(theta_cap=cap)
    print(f"{name:<28}${r['final']:>10,.0f}{100*r['cagr']:>6.1f}%{100*r['mddp']:>7.1f}%"
          f"{r['mar']:>6.2f}{r['taken']:>7}{r['skip_theta']:>7}{100*r['max_theta_pct']:>8.2f}%")
print("\nRead: if 'skipΘ'=0 and maxΘ/eq << 3%, the 3% cap NEVER binds (curve identical).")
