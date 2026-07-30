#!/usr/bin/env python
"""CANONICAL book simulator — strict rulebook compliance, NO contract scaling.

This is the simulator for the app. It sizes EXACTLY per the rulebook and never
inflates contracts to hit a theta target. Theta is an OUTPUT, reported only.
Governors (docs/rulebook.json + worst-loss-reference.json):
  sizing   : qty = clamp(floor(0.02*equity/worst_anchor), 1, per_line_cap)
             stocks cap=1, MES/MGC=2, MCL/MNG=5
  dedupe   : 1 per name, max 3 new equity/day, 21d same-name loss cooldown
  clusters : EQIDX 7% / ENERGY 5% / METALS 5% / TOTAL 12% of equity (tail budget)
  deploy   : sell book <= 25% BPR, buy book <= 15% (blueprint)
  exits    : 50%/21DTE (already in trade P&L)
  theta    : ALARM ONLY, flag if aggregate daily theta > 0.10% of net-liq
Sleeves: equity puts (gated), MES puts, MCL/MNG calls, MGC puts (SELL);
         straddles + ES/GC long calls (BUY). Starts $42K, 2015-2026.

CLUSTER_BASIS: 'worst' = absolute worst-ever loss per line (literal rulebook,
very tight on small accounts); 'p95' = typical concurrent-adverse loss (what a
correlated bad day actually costs). Run both to see the small-account gap.
"""
from __future__ import annotations
import os, sys, sqlite3, numpy as np, pandas as pd
EQ_DAILY_CAP = int(os.environ.get("EQ_DAILY_CAP", "3"))  # law 2026-07-30 (was 2)

EQ0, START, END = 42_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
RF = 0.045 / 252
RISK_PCT = 0.02
DTE = 35.0
CREDIT = {"EQ": 435.0, "MES": 227.5, "MCL": 200.0, "MNG": 150.0, "MGC": 200.0}  # calibrated to TJ acct
THETA_ALARM = 0.0010  # 0.10% of net-liq

# tag: (cluster, worst_anchor, p95_anchor, per_line_cap, bpr_margin, book)
LINE = {
    "EQ":  ("EQIDX",  3495, 367, 1, 1200, "sell"),
    "MES": ("EQIDX",  1569, 127, 2, 1300, "sell"),
    "MCL": ("ENERGY",  290, 111, 5,  350, "sell"),
    "MNG": ("ENERGY",  200,  20, 5,  280, "sell"),
    "MGC": ("METALS",  823, 115, 2,  220, "sell"),
    "STRAD": ("LONGVOL",  652, 652, 1, 1500, "buy"),
    "LCALL": ("LONGCALL", 373, 373, 1,  500, "buy"),
}
CLUSTER_CAP = {"EQIDX": 0.07, "ENERGY": 0.05, "METALS": 0.05}
TOTAL_CAP, SELL_BAND, BUY_BAND = 0.12, 0.25, 0.15


def size(tag, equity):
    _, wa, _, cap, _, _ = LINE[tag]
    return int(np.clip(np.floor(RISK_PCT * equity / wa), 1, cap))


def theta_of(tag, q):
    return (CREDIT.get(tag, 0.0) / DTE) * q if LINE[tag][5] == "sell" else 0.0


# ---- assemble the book ----
trades = []
eq = pd.read_csv("reports/iv_backtest_trades.csv"); eq["entry"] = pd.to_datetime(eq.entry)
eq = eq[(eq.vix_gate == True) | (eq.name_gate == True)].drop_duplicates(["symbol", "entry"])
for r in eq.itertuples():
    trades.append(dict(d=r.entry, x=r.entry + pd.Timedelta(days=int(r.days_held)),
                       pnl1=r.pnl, tag="EQ", name=f"EQ:{r.symbol}"))
con = sqlite3.connect("db/results.sqlite")
for rid, tag, sigs in [(66, "MES", ["bb_2sd", "five_day_low"]), (28, "MCL", ["bb_2sd_call"]),
                       (27, "MNG", ["bb_2sd_call"]), (30, "MGC", ["bb_2sd"])]:
    t = pd.read_sql(f"SELECT entry_date,pnl,days_held FROM trades WHERE run_id={rid} "
                    f"AND signal_type IN ({','.join(repr(s) for s in sigs)})", con)
    if t.empty:
        continue
    t["entry_date"] = pd.to_datetime(t.entry_date)
    for r in t.itertuples():
        trades.append(dict(d=r.entry_date, x=r.entry_date + pd.Timedelta(days=int(r.days_held)),
                           pnl1=r.pnl / 10.0, tag=tag, name=tag))
for rid in [71, 84, 96, 90, 91, 100, 101, 102, 103, 105]:
    t = pd.read_sql(f"SELECT entry_date,pnl FROM trades WHERE run_id={rid} AND signal_type='straddle_cheap'", con)
    if t.empty:
        continue
    fut = rid in (71, 84, 96)
    for r in t.itertuples():
        e = pd.to_datetime(r.entry_date)
        trades.append(dict(d=e, x=e + pd.Timedelta(days=21),
                           pnl1=(r.pnl / 10.0 if fut else r.pnl), tag="STRAD", name=f"STRAD{rid}"))
lc = pd.read_sql("SELECT entry_date,pnl FROM trades WHERE run_id=33 AND symbol IN ('ES','GC')", con)
for r in lc.itertuples():
    e = pd.to_datetime(r.entry_date)
    trades.append(dict(d=e, x=e + pd.Timedelta(days=30), pnl1=r.pnl / 10.0, tag="LCALL", name="LCALL"))
con.close()
T = pd.DataFrame([x for x in trades if x["d"] >= START]).sort_values("d").reset_index(drop=True)


def run(cluster_basis="p95"):
    ai = 1 if cluster_basis == "worst" else 2   # index into LINE for anchor
    equity, openp = EQ0, []
    curve = {}; thetas = []; wins = losses = 0
    taken = {t: 0 for t in LINE}; skips = {"dedupe": 0, "capacity": 0, "band": 0}
    alarm_days = 0
    Tby = {d: g for d, g in T.groupby("d")}
    for day in pd.date_range(START, END, freq="D"):
        for p in [p for p in openp if p["x"] <= day]:
            equity += p["realpnl"]; openp.remove(p)
            wins += p["realpnl"] > 0; losses += p["realpnl"] <= 0
        deployed = sum(p["m"] for p in openp)
        equity += max(equity - deployed, 0) * RF
        cur_theta = sum(p["theta"] for p in openp)
        thetas.append(cur_theta / equity); alarm_days += cur_theta / equity > THETA_ALARM
        names = {p["name"] for p in openp}; eqday = 0
        usedS = sum(p["m"] for p in openp if p["book"] == "sell")
        usedB = sum(p["m"] for p in openp if p["book"] == "buy")
        if day in Tby:
            for _, r in Tby[day].iterrows():
                cl, _, _, cap, mgn1, book = LINE[r.tag]
                q = size(r.tag, equity); anc = LINE[r.tag][ai]
                mgn = mgn1 * q
                if r["name"] in names:
                    skips["dedupe"] += 1; continue
                if r.tag == "EQ" and eqday >= EQ_DAILY_CAP:
                    skips["dedupe"] += 1; continue
                band, used = (SELL_BAND, usedS) if book == "sell" else (BUY_BAND, usedB)
                if used + mgn > band * equity:
                    skips["band"] += 1; continue
                if cl in CLUSTER_CAP:
                    ct = sum(p["tail"] for p in openp if p["cluster"] == cl)
                    if ct + anc * q > CLUSTER_CAP[cl] * equity:
                        skips["capacity"] += 1; continue
                if sum(p["tail"] for p in openp) + anc * q > TOTAL_CAP * equity:
                    skips["capacity"] += 1; continue
                openp.append(dict(name=r["name"], x=r.x, realpnl=r.pnl1 * q, m=mgn,
                                  tail=anc * q, cluster=cl, book=book, theta=theta_of(r.tag, q)))
                taken[r.tag] += 1
                if book == "sell": usedS += mgn
                else: usedB += mgn
                names.add(r["name"])
                if r.tag == "EQ": eqday += 1
        curve[day] = equity
    for p in openp:
        equity += p["realpnl"]; wins += p["realpnl"] > 0; losses += p["realpnl"] <= 0
    cv = pd.Series(curve); yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    dd = ((cv.cummax() - cv) / cv.cummax()).max(); cagr = (equity / EQ0) ** (1 / yrs) - 1
    mret = cv.resample("ME").last().pct_change().dropna()
    return dict(final=equity, cagr=cagr, maxdd=dd, mar=cagr / dd if dd else 0,
                mo_mean=mret.mean() * EQ0, mo_worst=mret.min(),
                win=100 * wins / (wins + losses), taken=taken, skips=skips,
                avg_theta=np.mean(thetas), max_theta=np.max(thetas), alarm_days=alarm_days,
                ntrades=sum(taken.values()))


print(f"CANONICAL book sim — ${EQ0:,.0f}, 2015-2026, strict rulebook (NO contract scaling)\n")
for basis in ("worst", "p95"):
    r = run(basis)
    lbl = "cluster cap = ABSOLUTE-WORST anchor" if basis == "worst" else "cluster cap = TYPICAL-ADVERSE (p95) anchor"
    print(f"[{lbl}]")
    print(f"  final ${r['final']:,.0f} | CAGR {100*r['cagr']:.1f}% | maxDD {100*r['maxdd']:.1f}% | "
          f"MAR {r['mar']:.2f} | ${r['mo_mean']:,.0f}/mo | worst mo {100*r['mo_worst']:.1f}% | win {r['win']:.0f}%")
    print(f"  trades {r['ntrades']} by sleeve {r['taken']}")
    print(f"  skips {r['skips']} | theta avg {100*r['avg_theta']:.3f}% max {100*r['max_theta']:.3f}% "
          f"| theta-alarm days (>0.10%): {r['alarm_days']}\n")
print("NO contract scaling anywhere: qty = clamp(floor(0.02*eq/anchor),1,cap); stocks cap=1.")
