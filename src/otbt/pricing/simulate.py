"""Phase-0 trade simulator.

Reconstructs a single short-option trade's P&L from the underlying price path
using Black-Scholes with the realized-vol proxy. Sigma is repriced each day
from trailing realized vol so downside vol expansion (the tail risk the book
cares about) is captured. Real IV (Databento) replaces this in Phase 1 for
exact dollars.

Management rules (charter defaults, all mechanical):
  - take profit at 50% of the entry credit
  - close at 21 DTE (the roll/close decision, taken mechanically as a close)
  - optional thesis-invalidation: close on daily close below the 100-EMA (H3)
  - else settle at expiration intrinsic
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import TRADE, COST
from .blackscholes import bs_price, strike_for_delta

VOL_FLOOR = 0.05          # guard against tiny/NaN realized vol
CONTRACT_MULT = 100       # equity options; futures override in Layer 2


@dataclass
class TradeResult:
    symbol: str
    signal_type: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    direction: str
    strike: float
    entry_spot: float
    entry_credit: float          # $/contract, net of costs
    pnl: float                   # $/contract, net of costs
    pnl_pct_credit: float        # pnl / gross credit
    mae: float                   # worst intra-trade $/contract (<=0 typ.)
    days_held: int
    exit_reason: str


def _round_costs(contracts: int = 1) -> float:
    per = COST.commission_per_contract + COST.exchange_fees_per_contract
    return per * contracts


def simulate_trade(df: pd.DataFrame, entry_date: pd.Timestamp, direction: str,
                   signal_type: str, symbol: str,
                   invalidation_below_ema100: bool = False,
                   trade=TRADE) -> TradeResult | None:
    """Simulate one trade. `df` must be a prepped frame (has close, ema100,
    rvol20) indexed by date and cover entry_date .. expiration.
    """
    if entry_date not in df.index:
        return None
    entry = df.loc[entry_date]
    sigma0 = max(float(entry["rvol20"]) if pd.notna(entry["rvol20"]) else VOL_FLOOR, VOL_FLOOR)
    S0 = float(entry["close"])
    kind = "put" if direction == "put" else "call"

    T0 = trade.dte_target / 365.0
    K = strike_for_delta(S0, T0, sigma0, trade.target_delta, kind=kind)
    gross_credit = bs_price(S0, K, T0, sigma0, kind=kind) * CONTRACT_MULT
    if gross_credit <= 0:
        return None

    expiration = entry_date + pd.Timedelta(days=trade.dte_target)
    path = df.loc[entry_date:expiration]

    slip = COST.slippage_ticks * CONTRACT_MULT          # $/contract per side
    entry_credit_net = gross_credit - slip - _round_costs()

    tp_target_value = gross_credit * (1 - trade.take_profit_pct)  # buy back at half credit
    worst_pnl = 0.0
    exit_reason = "expiration"
    exit_date = path.index[-1]
    exit_value = None

    for dt in path.index[1:]:                            # start day after entry
        row = df.loc[dt]
        S = float(row["close"])
        dte = (expiration - dt).days
        sigma = max(float(row["rvol20"]) if pd.notna(row["rvol20"]) else sigma0, VOL_FLOOR)
        if dte <= 0:
            opt_val = max((K - S) if kind == "put" else (S - K), 0.0) * CONTRACT_MULT
        else:
            opt_val = bs_price(S, K, dte / 365.0, sigma, kind=kind) * CONTRACT_MULT

        cur_pnl = gross_credit - opt_val
        worst_pnl = min(worst_pnl, cur_pnl)

        if opt_val <= tp_target_value:
            exit_reason, exit_date, exit_value = "take_profit_50", dt, tp_target_value
            break
        if invalidation_below_ema100 and S < float(row["ema100"]):
            exit_reason, exit_date, exit_value = "below_100ema", dt, opt_val
            break
        if dte <= trade.manage_dte:
            exit_reason, exit_date, exit_value = "manage_21dte", dt, opt_val
            break
    else:
        last = df.loc[exit_date]
        Sx = float(last["close"])
        exit_value = max((K - Sx) if kind == "put" else (Sx - K), 0.0) * CONTRACT_MULT

    pnl = gross_credit - exit_value - 2 * slip - _round_costs(2)   # both sides
    return TradeResult(
        symbol=symbol, signal_type=signal_type, entry_date=entry_date,
        exit_date=exit_date, direction=direction, strike=K, entry_spot=S0,
        entry_credit=entry_credit_net, pnl=pnl,
        pnl_pct_credit=pnl / gross_credit,
        mae=worst_pnl, days_held=(exit_date - entry_date).days,
        exit_reason=exit_reason,
    )
