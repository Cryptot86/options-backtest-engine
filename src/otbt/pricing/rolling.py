"""Tom-style rolling defense, honestly accounted (task #9 / H3 as-executed).

Rules simulated:
  - enter short 16d option as usual
  - at 21 DTE without hitting the chain target, ROLL OUT: buy back the
    current option at settlement and sell the SAME STRIKE in the next cycle
    (expiry nearest 40 DTE, monthly fallback) — the tasty "roll for a credit"
    (same strike, later expiry is always a credit)
  - chain closes when cumulative P&L >= 50% of ALL credits collected,
    or after max_rolls, or at final expiration

HONEST ACCOUNTING: the whole chain is ONE trade — total P&L from first entry
to final exit, peak MAE across the entire chain, total days tied up. No
win-rate inflation from counting each roll as its own "winning trade".
"""
from __future__ import annotations

import pandas as pd

from ..config import TRADE, COST
from . import glbx_options as gx


def _find_same_strike(fut_root, day, strike, kind, dte_min=30, dte_max=45):
    """Locate the same strike in the next cycle (nearest-40-DTE expiry with
    the monthly >=40 fallback). Returns (raw_symbol, expiration, underlying)."""
    defs = gx.get_option_definitions(fut_root, day)
    if defs.empty:
        return None
    cls = "P" if kind == "put" else "C"
    o = defs[defs["instrument_class"] == cls].copy()
    o["dte"] = (o["expiration"].dt.normalize() - day).dt.days
    w = o[(o["dte"] >= dte_min) & (o["dte"] <= dte_max)]
    if w.empty:
        w = o[(o["dte"] >= 40) & (o["dte"] <= 75)]
    if w.empty:
        return None
    exp = w.iloc[(w["dte"] - 40).abs().argsort().iloc[0]]["dte"]
    w = w[w["dte"] == exp]
    r = w.iloc[(w["strike_price"] - strike).abs().argsort().iloc[0]]
    return str(r["raw_symbol"]), pd.Timestamp(r["expiration"]).normalize(), str(r["underlying"])


def simulate_rolling_chain(fut_root, entry_date, cont_df, signal_type, iv_proxy,
                           kind="put", max_rolls=4, trade=TRADE):
    """One roll-chain = one trade. Returns a FutTradeResult-compatible object."""
    mult = gx.FUT_SPECS[fut_root]["mult"]
    tick = gx.FUT_SPECS[fut_root].get("opt_tick_usd", 10.0)
    fee = COST.commission_per_contract + COST.exchange_fees_per_contract
    entry_date = pd.Timestamp(entry_date).normalize()
    if entry_date not in cont_df.index:
        return None

    sel = gx.select_delta_option(fut_root, entry_date, iv_proxy, kind=kind,
                                 dte_min=trade.dte_min, dte_max=trade.dte_max,
                                 dte_target=trade.dte_target,
                                 target_delta=trade.target_delta)
    if sel is None:
        return None

    cash = 0.0            # net premium collected minus buybacks, $/contract units
    costs = 0.0           # slippage+fees accumulated in $
    total_credits = 0.0   # sum of all credits received (for the 50% target)
    worst_pnl = 0.0
    rolls = 0
    cur_sym, cur_exp, cur_und, cur_K = sel.raw_symbol, sel.expiration, sel.underlying, sel.strike
    first_credit = None
    day = entry_date
    exit_reason = "chain_expiry"

    def _result():
        pnl = cash * mult - costs
        from .glbx_options import FutTradeResult
        return FutTradeResult(
            symbol=fut_root, signal_type=f"{signal_type}|roll",
            entry_date=entry_date, exit_date=pd.Timestamp(day),
            strike=cur_K, dte=int((day - entry_date).days),
            entry_iv=float("nan"), entry_delta=float("nan"),
            entry_credit=(first_credit or 0.0) * mult,
            pnl=pnl, pnl_pct_credit=pnl / (total_credits * mult) if total_credits else 0.0,
            mae=worst_pnl, days_held=int((day - entry_date).days),
            exit_reason=f"{exit_reason}({rolls} rolls)")

    while True:
        path = gx.get_option_path(cur_sym, day, cur_exp)
        if path.empty:
            return None if first_credit is None else _result()
        path = path.set_index("date")["mid"].sort_index()
        if day not in path.index:
            if first_credit is None:
                return None
            break
        px0 = float(path.loc[day])
        if px0 <= 0:
            break
        cash += px0
        total_credits += px0
        costs += tick + fee
        if first_credit is None:
            first_credit = px0

        days = cont_df.loc[day:cur_exp].index
        last_opt, closed = px0, False
        for dt in days[1:]:
            if dt in path.index:
                last_opt = float(path.loc[dt])
            chain_pnl = (cash - last_opt) * mult - costs
            worst_pnl = min(worst_pnl, chain_pnl)
            dte = (cur_exp - dt).days
            if chain_pnl >= trade.take_profit_pct * total_credits * mult:
                cash -= last_opt; costs += tick + fee
                day, exit_reason, closed = dt, "chain_target", True
                break
            if dte <= trade.manage_dte:
                cash -= last_opt; costs += tick + fee     # buy back to roll/close
                day, closed = dt, True
                if rolls >= max_rolls:
                    exit_reason = "max_rolls"
                break
        if not closed:                                   # rode to expiration
            Fx = float(cont_df.loc[days[-1], "close"])
            intr = max(cur_K - Fx, 0.0) if kind == "put" else max(Fx - cur_K, 0.0)
            cash -= intr
            day = days[-1]
            break
        if exit_reason in ("chain_target", "max_rolls"):
            break
        # roll out: same strike, next cycle
        nxt = _find_same_strike(fut_root, day, cur_K, kind,
                                trade.dte_min, trade.dte_max)
        if nxt is None:
            exit_reason = "no_next_cycle"
            break
        rolls += 1
        cur_sym, cur_exp, cur_und = nxt

    return _result()
