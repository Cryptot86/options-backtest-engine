#!/usr/bin/env python
"""THETA-TARGET sim — 'if we operate at X% daily theta, what do we KEEP per month?'

Answers with REAL backtest P&L on $42K start, 2015-2026. The 50% profit target and
the win rate are ALREADY in the trade data (every trade exits 50%/21DTE). We scale
the whole book's sizing to hit each daily-theta target, then run the actual trades
and report monthly net + drawdown. NO forward assumptions — the losers are real.

Theta proxy (our store has no entry theta): equity 16d put credit ~= 2% of
strike*100; futures fixed credit/contract; theta = credit / DTE(40). SHORT book
only. Live app should re-verify with real chain theta (real account shows ~0.16%).
"""
from __future__ import annotations
import os, sqlite3, numpy as np, pandas as pd

EQ0, START, END = 42_000.0, pd.Timestamp("2015-01-01"), pd.Timestamp("2026-06-30")
RF = 0.045 / 252                # SGOV ~4.5% on idle
DTE = 35.0
# CALIBRATED to TJ's real tastytrade account (2026-07-30): theta ~= Cst(credit)/DTE.
# Observed per-position credit (Cst): INTC 540, CRDO 720, MU 200, NVDA 282 -> eq avg
# ~$435; /MES 227.50. Old proxy (2% of notional ~$100-250) understated theta ~2.5-3x.
CREDIT_EQ = 435.0               # flat avg credit per equity position (calibrated)
CREDIT_FUT = {"MES": 227.5, "MCL": 200.0, "MNG": 150.0, "MGC": 200.0}
LINE = {"EQ": ("EQIDX", 4520, 1200, 1), "MES": ("EQIDX", 1569, 1300, 2),
        "MCL": ("ENERGY", 290, 350, 5), "MNG": ("ENERGY", 200, 280, 5),
        "MGC": ("METALS", 823, 220, 2)}
BASECAP = {"ENERGY": 0.05, "METALS": 0.05, "EQIDX": 0.07}


def base_qty(tag, equity):
    _, anc, _, cap = LINE[tag]
    return max(1, int(np.floor(0.02 * equity / anc)))     # cap applied after scale


def theta_of(tag, strike, contracts):
    credit = CREDIT_EQ if tag == "EQ" else CREDIT_FUT.get(tag, 150.0)
    return (credit / DTE) * contracts


# ---- assemble book ----
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
con.close()
T = pd.DataFrame([x for x in trades if x["d"] >= START]).sort_values("d").reset_index(drop=True)


def run(scale=1.0):
    CAP = {k: v * scale for k, v in BASECAP.items()}
    equity, openp = EQ0, []
    curve = {}; thetas = []; wins = losses = 0
    Tby = {d: g for d, g in T.groupby("d")}
    for day in pd.date_range(START, END, freq="D"):
        for p in [p for p in openp if p["x"] <= day]:
            equity += p["realpnl"]; openp.remove(p)
            if p["realpnl"] > 0: wins += 1
            else: losses += 1
        deployed = sum(p["m"] for p in openp)
        equity += max(equity - deployed, 0) * RF
        cur_theta = sum(p["theta"] for p in openp)
        thetas.append(cur_theta / equity)
        names = {p["name"] for p in openp}; eqday = 0
        usedS = sum(p["m"] for p in openp)
        if day in Tby:
            for _, r in Tby[day].iterrows():
                q = int(np.clip(np.floor(base_qty(r.tag, equity) * scale), 1, LINE[r.tag][3] * max(1, round(scale))))
                mgn = r.margin * q; ok = True
                if r["name"] in names: ok = False
                if r.tag == "EQ" and eqday >= 2: ok = False
                if usedS + mgn > 0.50 * scale * equity: ok = False
                if r.cluster in CAP:
                    ct = sum(p["tail"] for p in openp if p["cluster"] == r.cluster)
                    if ct + LINE[r.tag][1] * q > CAP[r.cluster] * equity: ok = False
                if ok:
                    openp.append(dict(name=r["name"], x=r.x, realpnl=r.pnl1 * q, m=mgn,
                                      tail=LINE[r.tag][1] * q, cluster=r.cluster,
                                      theta=theta_of(r.tag, r.strike, q)))
                    usedS += mgn; names.add(r["name"])
                    if r.tag == "EQ": eqday += 1
        curve[day] = equity
    for p in openp:
        equity += p["realpnl"]
        if p["realpnl"] > 0: wins += 1
        else: losses += 1
    cv = pd.Series(curve); yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    dd = ((cv.cummax() - cv) / cv.cummax()).max()
    cagr = (equity / EQ0) ** (1 / yrs) - 1
    mret = cv.resample("ME").last().pct_change().dropna()
    return dict(scale=scale, final=equity, cagr=cagr, maxdd=dd, mar=cagr / dd if dd else 0,
                avg_theta=np.mean(thetas), max_theta=np.max(thetas),
                mo_mean=mret.mean(), mo_worst=mret.min(),
                win=100 * wins / (wins + losses) if (wins + losses) else 0)


# calibrate: measure base avg theta at scale 1, then pick scales for target avg-theta levels
base = run(1.0)
print(f"book on ${EQ0:,.0f}, 2015-2026 | base(scale 1): avg theta {100*base['avg_theta']:.3f}%/day, "
      f"max {100*base['max_theta']:.3f}% | win {base['win']:.0f}%\n")
targets = [0.02, 0.05, 0.10, 0.16, 0.25]   # % of equity/day (avg)
scales = [t / 100 / base['avg_theta'] for t in targets]
print(f"{'target Θ/day':>12}{'~scale':>8}{'avgΘ':>7}{'maxΘ':>7}"
      f"{'$/mo(mean)':>12}{'%/mo':>7}{'worst mo':>9}{'maxDD':>7}{'MAR':>6}{'CAGR':>7}")
print(f"{'VALIDATED':>11} {1.0:>8.1f}{100*base['avg_theta']:>6.2f}%{100*base['max_theta']:>6.2f}%"
      f"${base['mo_mean']*EQ0:>10,.0f}{100*base['mo_mean']:>6.2f}%{100*base['mo_worst']:>8.1f}%"
      f"{100*base['maxdd']:>6.1f}%{base['mar']:>6.2f}{100*base['cagr']:>6.1f}%")
for tgt, sc in zip(targets, scales):
    r = run(sc)
    mo_dollar = r['mo_mean'] * EQ0
    print(f"{tgt:>11.2f}%{sc:>8.1f}{100*r['avg_theta']:>6.2f}%{100*r['max_theta']:>6.2f}%"
          f"${mo_dollar:>10,.0f}{100*r['mo_mean']:>6.2f}%{100*r['mo_worst']:>8.1f}%"
          f"{100*r['maxdd']:>6.1f}%{r['mar']:>6.2f}{100*r['cagr']:>6.1f}%")
print("\n'$/mo(mean)' = mean monthly return applied to $42K. 'worst mo' = deepest single "
      "month. 50%-target & win rate are ALREADY in the trade P&L. Higher Θ = more $/mo "
      "AND more drawdown — read maxDD and worst-mo, not just $/mo.")
