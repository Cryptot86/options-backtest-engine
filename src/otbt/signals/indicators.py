"""Vectorized technical indicators used by the signal engine.

All functions take/return pandas Series aligned to a price DataFrame's index.
Kept dependency-free (pandas/numpy only) so results are reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def bollinger(close: pd.Series, window: int = 20, num_sd: float = 2.0):
    """Return (mid, upper, lower) Bollinger bands."""
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    upper = mid + num_sd * sd
    lower = mid - num_sd * sd
    return mid, upper, lower


def realized_vol(close: pd.Series, window: int = 20, trading_days: int = 252) -> pd.Series:
    """Annualized trailing realized volatility (close-to-close log returns).

    This is the Phase-0 IV stand-in; Layer 2 replaces it with real IV where
    exact dollar expectancy matters (H6/H11).
    """
    logret = np.log(close / close.shift(1))
    return logret.rolling(window).std(ddof=0) * np.sqrt(trading_days)


def rolling_low(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).min()


def local_extrema_flags(series: pd.Series, order: int = 3):
    """Boolean Series marking local minima / maxima using a symmetric window.

    A point is a local min if it is <= all points within +/- `order` bars.
    Used for RSI-divergence pivot detection.
    """
    n = len(series)
    is_min = pd.Series(False, index=series.index)
    is_max = pd.Series(False, index=series.index)
    vals = series.values
    for i in range(order, n - order):
        window = vals[i - order:i + order + 1]
        c = vals[i]
        if np.isnan(c):
            continue
        if c == np.nanmin(window):
            is_min.iloc[i] = True
        if c == np.nanmax(window):
            is_max.iloc[i] = True
    return is_min, is_max
