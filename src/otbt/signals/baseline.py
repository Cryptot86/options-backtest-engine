"""H6 — naive VRP baseline signal generator.

Sell a 16-delta put whenever volatility is 'rich': the trailing realized-vol
proxy sits in a high percentile of its own 1-year history (IV-rank stand-in).
No technical indicator. This is the yardstick every H1-H5 method must beat.

In Phase 1 the iv-rank proxy is replaced by real IV rank and the IV-RV spread.
Entries are throttled to at most one per `min_gap_days` per symbol so the
baseline isn't dominated by dense overlapping trades.
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind


def generate_baseline(prices: dict[str, pd.DataFrame],
                      iv_rank_min: float = 0.50,
                      lookback: int = 252,
                      min_gap_days: int = 7,
                      require_trend_up: bool = False) -> pd.DataFrame:
    rows = []
    for symbol, df in prices.items():
        close = df["close"]
        rvol = ind.realized_vol(close, 20)
        # IV-rank proxy: percentile rank of today's rvol within trailing window.
        iv_rank = rvol.rolling(lookback).apply(
            lambda w: (w[-1] >= w).mean(), raw=True)
        ema10, ema100 = ind.ema(close, 10), ind.ema(close, 100)
        trend_up = ema10 > ema100

        eligible = iv_rank >= iv_rank_min
        if require_trend_up:
            eligible &= trend_up

        last_entry = None
        for dt in df.index[eligible.fillna(False)]:
            if last_entry is not None and (dt - last_entry).days < min_gap_days:
                continue
            last_entry = dt
            rows.append({
                "symbol": symbol, "date": dt, "signal_type": "vrp_baseline",
                "direction": "put", "spot": float(close.loc[dt]),
                "trend_up": bool(trend_up.loc[dt]),
                "iv_proxy": float(rvol.loc[dt]) if pd.notna(rvol.loc[dt]) else None,
                "meta": {"iv_rank": float(iv_rank.loc[dt])},
            })
    ledger = pd.DataFrame(rows)
    if not ledger.empty:
        ledger = ledger.sort_values(["symbol", "date"]).reset_index(drop=True)
    return ledger
