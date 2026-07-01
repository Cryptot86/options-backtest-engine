"""Real-IV trade simulator (Phase 1).

Unlike the Phase-0 BS reconstruction, this walks the option's ACTUAL daily
closes from Databento through the mechanical management rules:
  - take profit at 50% of the entry credit (buy back at half price)
  - close at 21 DTE
  - optional thesis-invalidation: underlying closes below its 100-EMA (H3)
  - else settle at expiration intrinsic

Missing option days (degraded/no-trade) are forward-filled from the last mark.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import TRADE, COST
from . import databento_options as dbo

CONTRACT_MULT = 100


@dataclass
class RealTradeResult:
    symbol: str
    signal_type: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    strike: float
    dte: int
    entry_iv: float
    entry_delta: float
    entry_credit: float      # $/contract net
    pnl: float               # $/contract net
    pnl_pct_credit: float
    mae: float
    days_held: int
    exit_reason: str


def _costs_per_side(contracts=1):
    return (COST.commission_per_contract + COST.exchange_fees_per_contract) * contracts


def simulate_real_trade(symbol, entry_date, underlying_df, signal_type,
                        iv_proxy, invalidation_below_ema100=False,
                        trade=TRADE) -> RealTradeResult | None:
    entry_date = pd.Timestamp(entry_date).normalize()
    spot = float(underlying_df.loc[entry_date, "close"]) if entry_date in underlying_df.index else None
    if spot is None:
        return None

    sel = dbo.select_16delta_put(symbol, entry_date, spot, iv_proxy,
                                 dte_min=trade.dte_min, dte_max=trade.dte_max,
                                 dte_target=trade.dte_target,
                                 target_delta=trade.target_delta, neighbors=2)
    if sel is None:
        return None

    expiration = sel.expiration.normalize()
    path = dbo.get_symbol_path(sel.raw_symbol, entry_date, expiration)
    if path.empty:
        return None
    path = path.set_index("date").sort_index()

    gross_credit = sel.price * CONTRACT_MULT
    slip = COST.slippage_ticks * CONTRACT_MULT
    entry_credit_net = gross_credit - slip - _costs_per_side()
    tp_price = sel.price * (1 - trade.take_profit_pct)   # buy back at half

    # walk the underlying trading days; forward-fill option marks over gaps
    days = underlying_df.loc[entry_date:expiration].index
    last_opt = sel.price
    worst_pnl = 0.0
    exit_reason, exit_date, exit_opt = "expiration", days[-1], None

    for dt in days[1:]:
        if dt in path.index:
            last_opt = float(path.loc[dt, "close"])
        opt = last_opt
        dte = (expiration - dt).days
        cur_pnl = (sel.price - opt) * CONTRACT_MULT
        worst_pnl = min(worst_pnl, cur_pnl)

        if opt <= tp_price:
            exit_reason, exit_date, exit_opt = "take_profit_50", dt, tp_price
            break
        if invalidation_below_ema100 and dt in underlying_df.index \
                and float(underlying_df.loc[dt, "close"]) < float(underlying_df.loc[dt, "ema100"]):
            exit_reason, exit_date, exit_opt = "below_100ema", dt, opt
            break
        if dte <= trade.manage_dte:
            exit_reason, exit_date, exit_opt = "manage_21dte", dt, opt
            break

    if exit_opt is None:   # held to expiration -> intrinsic on underlying
        Sx = float(underlying_df.loc[exit_date, "close"])
        exit_opt = max(sel.strike - Sx, 0.0)

    exit_val = exit_opt * CONTRACT_MULT
    pnl = gross_credit - exit_val - 2 * slip - _costs_per_side(2)
    return RealTradeResult(
        symbol=symbol, signal_type=signal_type, entry_date=entry_date,
        exit_date=pd.Timestamp(exit_date), strike=sel.strike, dte=sel.dte,
        entry_iv=sel.iv, entry_delta=sel.delta, entry_credit=entry_credit_net,
        pnl=pnl, pnl_pct_credit=pnl / gross_credit if gross_credit else 0.0,
        mae=worst_pnl, days_held=(pd.Timestamp(exit_date) - entry_date).days,
        exit_reason=exit_reason,
    )
