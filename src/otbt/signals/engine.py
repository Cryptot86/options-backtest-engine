"""Layer 1 signal engine.

Consumes underlying OHLC and emits a signal ledger with one row per
entry event:

    symbol, date, signal_type, direction, spot, trend_up, iv_proxy, meta

`direction` is the side we SELL: "put" (bullish/neutral) or "call" (bearish).
`trend_up` is the 10-EMA > 100-EMA filter (H10). `iv_proxy` is trailing
realized vol, the Phase-0 IV stand-in used for baseline/gating studies until
real IV is wired in (Layer 2).

Signal types implemented:
    rsi_divergence  (H1)  bullish RSI divergence in an uptrend -> sell put
    bb_2sd          (H2)  close <= lower 2-SD band + uptrend      -> sell put
    bounce_100ema   (H3)  touch 100-EMA from above + uptrend      -> sell put
    bb_20sma        (H4)  close <= lower band around 20-SMA        -> sell put
    five_day_low    (H5)  new 5-day low in an uptrend              -> sell put
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind


LEDGER_COLUMNS = [
    "symbol", "date", "signal_type", "direction",
    "spot", "trend_up", "iv_proxy", "meta",
]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the shared indicator columns used across signals."""
    out = df.copy()
    close = out["close"]
    out["ema10"] = ind.ema(close, 10)
    out["ema100"] = ind.ema(close, 100)
    out["rsi14"] = ind.rsi(close, 14)
    mid20, up20, lo20 = ind.bollinger(close, 20, 2.0)
    out["bb_mid"] = mid20
    out["bb_lower"] = lo20
    out["rvol20"] = ind.realized_vol(close, 20)
    out["trend_up"] = out["ema10"] > out["ema100"]
    return out


def _row(symbol, dt, signal_type, direction, spot, trend_up, iv_proxy, **meta):
    return {
        "symbol": symbol, "date": dt, "signal_type": signal_type,
        "direction": direction, "spot": float(spot),
        "trend_up": bool(trend_up), "iv_proxy": float(iv_proxy) if pd.notna(iv_proxy) else None,
        "meta": meta,
    }


def _bb_2sd(symbol: str, df: pd.DataFrame) -> list[dict]:
    """H2: close at/below lower 2-SD band while in uptrend (10 EMA > 100 EMA)."""
    rows = []
    hit = (df["close"] <= df["bb_lower"]) & df["trend_up"]
    # entry only on the first bar of a touch cluster (avoid duplicate entries)
    entry = hit & ~hit.shift(1, fill_value=False)
    for dt in df.index[entry]:
        r = df.loc[dt]
        rows.append(_row(symbol, dt, "bb_2sd", "put", r["close"], r["trend_up"],
                         r["rvol20"], band=float(r["bb_lower"])))
    return rows


def _bb_20sma(symbol: str, df: pd.DataFrame) -> list[dict]:
    """H4: price at lower band around the 20 SMA (expected structural loser).

    Distinguished from H2 by using a shallower 1-SD band around the 20-SMA,
    the 'shallow level price punches through to the 100 EMA' setup.
    """
    rows = []
    mid, _, lower1 = ind.bollinger(df["close"], 20, 1.0)
    hit = (df["close"] <= lower1) & df["trend_up"]
    entry = hit & ~hit.shift(1, fill_value=False)
    for dt in df.index[entry]:
        r = df.loc[dt]
        rows.append(_row(symbol, dt, "bb_20sma", "put", r["close"], r["trend_up"],
                         r["rvol20"], band=float(lower1.loc[dt])))
    return rows


def _bounce_100ema(symbol: str, df: pd.DataFrame, touch_pct: float = 0.01) -> list[dict]:
    """H3: price touches 100-EMA from above WITH trend (10 > 100).

    Touch = low within touch_pct of the 100-EMA while the prior close was
    above it. Exit logic (50% OR close < 100EMA) lives in Layer 2/3.
    """
    rows = []
    above_prior = df["close"].shift(1) > df["ema100"].shift(1)
    touch = (df["low"] <= df["ema100"] * (1 + touch_pct)) & (df["close"] >= df["ema100"])
    hit = above_prior & touch & df["trend_up"]
    entry = hit & ~hit.shift(1, fill_value=False)
    for dt in df.index[entry]:
        r = df.loc[dt]
        rows.append(_row(symbol, dt, "bounce_100ema", "put", r["close"], r["trend_up"],
                         r["rvol20"], ema100=float(r["ema100"])))
    return rows


def _five_day_low(symbol: str, df: pd.DataFrame) -> list[dict]:
    """H5: new 5-day closing low while in an uptrend."""
    rows = []
    ll = ind.rolling_low(df["close"], 5)
    hit = (df["close"] <= ll) & df["trend_up"]
    entry = hit & ~hit.shift(1, fill_value=False)
    for dt in df.index[entry]:
        r = df.loc[dt]
        rows.append(_row(symbol, dt, "five_day_low", "put", r["close"], r["trend_up"],
                         r["rvol20"]))
    return rows


def _rsi_divergence(symbol: str, df: pd.DataFrame, lookback: int = 40,
                    order: int = 3) -> list[dict]:
    """H1: price makes a lower low while RSI makes a higher low, in uptrend.

    Compares consecutive price pivot-lows: bullish divergence when the newer
    price low < prior price low but the RSI at the newer low > RSI at prior low.
    """
    rows = []
    price_min, _ = ind.local_extrema_flags(df["close"], order=order)
    pivot_idx = list(df.index[price_min])
    for k in range(1, len(pivot_idx)):
        cur, prev = pivot_idx[k], pivot_idx[k - 1]
        if (cur - prev).days > lookback:
            continue
        pc, pp = df.loc[cur], df.loc[prev]
        if not pc["trend_up"]:
            continue
        lower_low = pc["close"] < pp["close"]
        rsi_higher = pc["rsi14"] > pp["rsi14"]
        if lower_low and rsi_higher:
            rows.append(_row(symbol, cur, "rsi_divergence", "put", pc["close"],
                             pc["trend_up"], pc["rvol20"],
                             prev_low=float(pp["close"]),
                             rsi_now=float(pc["rsi14"]), rsi_prev=float(pp["rsi14"])))
    return rows


_DETECTORS = {
    "bb_2sd": _bb_2sd,
    "bb_20sma": _bb_20sma,
    "bounce_100ema": _bounce_100ema,
    "five_day_low": _five_day_low,
    "rsi_divergence": _rsi_divergence,
}


def generate_signals(prices: dict[str, pd.DataFrame],
                     signal_types: list[str] | None = None) -> pd.DataFrame:
    """Run all (or selected) detectors across a universe -> signal ledger."""
    types = signal_types or list(_DETECTORS)
    all_rows: list[dict] = []
    for symbol, df in prices.items():
        prepped = _prep(df)
        for t in types:
            all_rows.extend(_DETECTORS[t](symbol, prepped))
    ledger = pd.DataFrame(all_rows, columns=LEDGER_COLUMNS)
    if not ledger.empty:
        ledger = ledger.sort_values(["symbol", "date"]).reset_index(drop=True)
    return ledger
