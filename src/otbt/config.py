"""Central configuration for the options-method backtest.

Values here encode the charter defaults (see memory/project-purpose.md):
default structure = sell 16-delta option, 30-45 DTE; manage 50% / 21 DTE;
no earnings holds; CVaR sizing caps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
# Phase-0 default equity/ETF set. Correct/extend once the real symbol list
# is confirmed. Futures roots are handled separately (Databento GLBX + Black-76).
DEFAULT_EQUITY_UNIVERSE: list[str] = [
    "SPY", "QQQ", "IWM", "DIA",          # broad index ETFs
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",  # large-cap names
    "XLE", "XLF", "GLD", "USO",          # sector / commodity ETFs
]

# CME futures roots the user trades (commodities + currency/"forex" futures).
# Placeholder list — confirm exact roots. Priced via Black-76 in Layer 2.
DEFAULT_FUTURES_ROOTS: list[str] = [
    "NG",   # natural gas
    "CL",   # crude oil
    "GC",   # gold
    "ZC",   # corn
    "6E",   # euro FX
    "6B",   # british pound FX
]

# Backtest window — must include the 2020 and 2022 vol events.
START_DATE = date(2015, 1, 1)
END_DATE = date(2025, 6, 30)


# ---------------------------------------------------------------------------
# Default trade structure & management (charter defaults)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TradeConfig:
    target_delta: float = 0.16          # sell 16-delta
    dte_min: int = 30
    dte_max: int = 45
    dte_target: int = 40
    take_profit_pct: float = 0.50       # close at 50% of max credit
    manage_dte: int = 21                # roll/close decision at 21 DTE
    no_earnings_holds: bool = True


# ---------------------------------------------------------------------------
# Sizing / risk (Tom's CVaR caps)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskConfig:
    account_size: float = 48_000.0
    defined_risk_cap_pct: float = 0.02          # <=2% of account, defined risk
    undefined_risk_cap_pct: float = 0.07        # <=5-7% undefined; use upper bound
    undefined_risk_cap_pct_low: float = 0.05

    @property
    def undefined_tail_dollars_low(self) -> float:
        return self.account_size * self.undefined_risk_cap_pct_low   # ~$2,400

    @property
    def undefined_tail_dollars_high(self) -> float:
        return self.account_size * self.undefined_risk_cap_pct       # ~$3,360


# ---------------------------------------------------------------------------
# Fees / slippage (realistic, per the "after fees" success criterion)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CostConfig:
    commission_per_contract: float = 0.65       # per option contract, per side
    exchange_fees_per_contract: float = 0.10
    slippage_ticks: float = 0.02                # $/share of mid-price slippage per side


TRADE = TradeConfig()
RISK = RiskConfig()
COST = CostConfig()

# Cache / output locations (relative to repo root).
DATA_CACHE_DIR = "data_cache"
OUTPUT_DIR = "output"
