#!/usr/bin/env python
"""Gate-0 RECONCILIATION — the manifest's paywall gate.

Take trades we ALREADY priced from Databento OPRA (run_id 74 = MSFT, 73 = AAPL,
both real-IV) and re-price the SAME contracts from IVolatility EOD. Replay the
SAME management rules with the SAME cost model (imported from the engine, not
re-derived). IVol must reproduce our P&L within +/-10% or the vendor is rejected
and the manifest is void.

Same contract. Same engine. Two vendors. If the P&L matches, the only thing
that changed is where the marks came from -> IVol is a trustworthy source and
we let the month bill. If it doesn't, we cancel inside the trial.

Usage:
  python gate0_reconcile.py                 # 20 trades: 10 MSFT + 10 AAPL
  python gate0_reconcile.py --n 30 --runs 74 73
  python gate0_reconcile.py --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import pandas as pd

from src.otbt.config import COST, TRADE
from src.otbt.pricing.simulate_real import CONTRACT_MULT, _costs_per_side
from src.otbt.pricing import ivol_client as iv

DB = "db/results.sqlite"
SLIP = COST.slippage_ticks * CONTRACT_MULT          # entry/exit slippage, $/contract
TOL_PCT = 0.10                                       # manifest kill bar
TOL_ABS = 5.0                                        # $ floor: tiny-P&L noise guard


def load_trades(runs, n) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    per = max(1, n // len(runs))
    frames = []
    for rid in runs:
        q = (f"SELECT symbol,entry_date,exit_date,strike,entry_credit,pnl,dte,"
             f"entry_delta,exit_reason FROM trades WHERE run_id={rid} "
             f"AND entry_credit IS NOT NULL AND dte IS NOT NULL "
             f"ORDER BY entry_date LIMIT {per}")
        f = pd.read_sql(q, con)
        if not f.empty:
            frames.append(f)
    con.close()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def our_entry_px(entry_credit_net: float) -> float:
    """Invert the engine's entry accounting to the per-share mark it paid on."""
    return (entry_credit_net + SLIP + _costs_per_side(1)) / CONTRACT_MULT


def replay_pnl(path: pd.DataFrame, entry_px: float, expiration, strike,
               exit_cap, exit_spot=None) -> tuple[float, float, str]:
    """The engine's management loop (mirror of simulate_real.py:93-140), run on
    IVol's daily closes. Returns (pnl, worst_mae, exit_reason). Walks only to
    exit_cap (the stored exit date) so trades that exited on underlying context
    (below_100ema) exit there at IVol's mark; TP/21DTE trigger earlier if hit."""
    tp = entry_px * (1 - TRADE.take_profit_pct)
    days = path.loc[:exit_cap].index
    last, worst = entry_px, 0.0
    exit_opt, reason = None, "at_stored_exit"
    for dt in days[1:]:
        opt = float(path.loc[dt, "close"]) if dt in path.index else last
        last = opt
        worst = min(worst, (entry_px - opt) * CONTRACT_MULT)
        dte = (pd.Timestamp(expiration) - dt).days
        if opt <= tp:
            exit_opt, reason = tp, "take_profit_50"; break
        if dte <= TRADE.manage_dte:
            exit_opt, reason = opt, "manage_21dte"; break
    if exit_opt is None:                              # reached the stored exit
        last_dt = days[-1]
        if pd.Timestamp(last_dt).normalize() >= pd.Timestamp(expiration).normalize() \
                and exit_spot is not None:
            exit_opt = max(strike - exit_spot, 0.0)   # expired -> intrinsic
        else:
            exit_opt = float(path.loc[last_dt, "close"])
    gross = entry_px * CONTRACT_MULT
    pnl = gross - exit_opt * CONTRACT_MULT - 2 * SLIP - _costs_per_side(2)
    return pnl, worst, reason


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--runs", nargs="*", type=int, default=[74, 73])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    trades = load_trades(a.runs, a.n)
    print(f"Reconciling {len(trades)} OPRA-priced trades vs IVol "
          f"(runs {a.runs}, tol +/-{int(TOL_PCT*100)}% or ${TOL_ABS:.0f})\n")

    if a.dry_run:
        print("DRY RUN — contracts we would re-price from IVol:")
        for _, t in trades.iterrows():
            exp = (pd.Timestamp(t.entry_date) + pd.Timedelta(days=int(t.dte))).date()
            print(f"  {t.symbol:<5} {t.entry_date}->{t.exit_date}  "
                  f"{'P' if t.entry_delta < 0 else 'C'} K={t.strike:g} exp~{exp} "
                  f"| our pnl={t.pnl:+.2f}")
        print("\nSet IVOL_API_KEY in .env, drop --dry-run, re-run.")
        return 0

    rows = []
    for i, t in enumerate(trades.itertuples(index=False), 1):
        right = "P" if t.entry_delta < 0 else "C"
        exp = pd.Timestamp(t.entry_date) + pd.Timedelta(days=int(t.dte))
        entry_px = our_entry_px(float(t.entry_credit))
        try:
            path = iv.option_series(t.symbol, exp.strftime("%Y-%m-%d"), float(t.strike),
                                    right, str(t.entry_date), str(t.exit_date))
            if path.empty or pd.Timestamp(t.entry_date) not in path.index:
                raise RuntimeError("no IVol mark on entry date")
            iv_entry = float(path.loc[pd.Timestamp(t.entry_date), "close"])
            iv_pnl, iv_mae, reason = replay_pnl(
                path, iv_entry, exp, float(t.strike), pd.Timestamp(t.exit_date))
            entry_diff = abs(iv_entry - entry_px) / entry_px if entry_px else float("nan")
            pnl_diff = abs(iv_pnl - t.pnl)
            tol = max(TOL_PCT * abs(t.pnl), TOL_ABS)
            ok = pnl_diff <= tol
            rows.append(dict(symbol=t.symbol, entry=t.entry_date, our_px=round(entry_px, 3),
                             ivol_px=round(iv_entry, 3), entry_diff_pct=round(100*entry_diff, 1),
                             our_pnl=round(t.pnl, 2), ivol_pnl=round(iv_pnl, 2),
                             pnl_diff=round(pnl_diff, 2), pass_=ok))
            print(f"[{i:>2}] {'PASS' if ok else 'FAIL'} {t.symbol:<5} {t.entry_date} "
                  f"entry our={entry_px:.2f} ivol={iv_entry:.2f} ({100*entry_diff:+.0f}%)  "
                  f"pnl our={t.pnl:+.1f} ivol={iv_pnl:+.1f} d=${pnl_diff:.1f}", flush=True)
        except Exception as e:
            rows.append(dict(symbol=t.symbol, entry=t.entry_date, our_px=round(entry_px, 3),
                             ivol_px=None, entry_diff_pct=None, our_pnl=round(t.pnl, 2),
                             ivol_pnl=None, pnl_diff=None, pass_=False))
            print(f"[{i:>2}] ERR  {t.symbol:<5} {t.entry_date}: {e}", flush=True)

    df = pd.DataFrame(rows)
    priced = df[df.ivol_pnl.notna()]
    n_pass = int(df.pass_.sum())
    print("\n================ GATE-0 RECONCILIATION ================")
    print(f"trades attempted : {len(df)}")
    print(f"priced by IVol   : {len(priced)}/{len(df)}")
    if len(priced):
        print(f"median entry-mark diff : {priced.entry_diff_pct.abs().median():.1f}%")
        print(f"pass within tol        : {n_pass}/{len(df)}")
    passed = len(df) and n_pass / len(df) >= 0.80 and len(priced) >= 0.80 * len(df)
    print("\nVERDICT:", "PASS — IVol reproduces our P&L. Let the month bill; proceed to Study 1."
          if passed else
          "FAIL — IVol does not reconcile. Cancel inside the trial; manifest void.")
    df.to_csv("reports/gate0_reconcile_result.csv", index=False)
    print("wrote reports/gate0_reconcile_result.csv")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
