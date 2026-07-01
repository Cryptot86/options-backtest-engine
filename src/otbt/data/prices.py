"""Underlying daily OHLC ingestion with local parquet caching.

Phase-0 equity/ETF prices come from yfinance (free). Futures continuous
series will come from Databento GLBX in Layer 2 and plug into the same
DataFrame contract: index=DatetimeIndex, columns=[open,high,low,close,volume].
"""
from __future__ import annotations

import os

import pandas as pd

from ..config import DATA_CACHE_DIR


def _cache_path(symbol: str) -> str:
    os.makedirs(DATA_CACHE_DIR, exist_ok=True)
    safe = symbol.replace("/", "_").replace("^", "_")
    return os.path.join(DATA_CACHE_DIR, f"{safe}.parquet")


def get_prices(symbol: str, start: str, end: str, refresh: bool = False) -> pd.DataFrame:
    """Return daily OHLCV for `symbol`, cached locally.

    Columns are lowercased to [open, high, low, close, volume]. Uses
    auto-adjusted prices so splits/dividends don't create fake gaps that
    would trigger spurious signals.
    """
    path = _cache_path(symbol)
    if os.path.exists(path) and not refresh:
        df = pd.read_parquet(path)
    else:
        import yfinance as yf

        raw = yf.download(
            symbol, start=start, end=end,
            auto_adjust=True, progress=False, actions=False,
        )
        if raw is None or raw.empty:
            raise ValueError(f"No price data returned for {symbol}")
        # yfinance may return a MultiIndex columns frame for a single ticker.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index)
        df.index.name = "date"
        df.to_parquet(path)
    return df


def get_universe_prices(symbols: list[str], start: str, end: str,
                        refresh: bool = False) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            out[sym] = get_prices(sym, start, end, refresh=refresh)
        except Exception as exc:  # keep going; report at the end
            print(f"[warn] {sym}: {exc}")
    return out
