"""IVolatility REST adapter — a DATA SOURCE, not a new engine.

Design contract (why this file exists):
  Our validated engine (pricing/simulate_real.py) consumes ONE thing per trade:
  a daily option-mark path  ->  DataFrame[index=date, columns=['close']].
  This module reproduces exactly that shape from IVolatility EOD data, so the
  engine runs verbatim and only the vendor changes. That is also what makes
  Gate-0 reconciliation meaningful: same contract, same engine, two vendors.

Endpoints locked from the official OpenAPI spec (IVolatility-com/API-docs):
  base                 https://restapi.ivolatility.com
  auth                 apiKey=<key>   OR   /token/get?username&password -> token
  stock EOD            /equities/eod/stocks-prices        symbol, from_, to
  option lookup        /proxy/option-series               symbol, expFrom, expTo,
                                                          strikeFrom, strikeTo, callPut
                       -> record.optionSymbol  (the option_id)
  option EOD series    /equities/eod/single-stock-option-raw-iv
                                                          option_id, from_, to
                       -> daily: date, iv, bid, ask (+ close/greeks/oi where present)
  IV index             /equities/eod/ivx                  symbol, from_, to

Flow for one contract's daily path: resolve optionSymbol via /proxy/option-series
(one call), then pull its whole series via single-stock-option-raw-iv (one call).

Throttle: 1 request/second (burst 5) — the plan rate limit; we self-limit.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("IVOL_BASE", "https://restapi.ivolatility.com")
EP_STOCK_EOD  = "/equities/eod/stock-prices"            # symbol, from, to
EP_OPT_SERIES = "/equities/eod/option-series-on-date"   # symbol, date, exp*/strike*/callPut -> optionId
EP_OPT_EOD    = "/equities/eod/single-stock-option-raw-iv"  # optionId, from, to
EP_IVX        = "/equities/eod/ivx"                      # symbol, from, to
EP_EARNINGS   = "/equities/eod/earnings"                 # symbol(s), from, to
EP_TOKEN      = "/token/get"

_RATE_SECONDS = 1.05
_lock = threading.Lock()
_last = [0.0]
_token = [None]     # cached bearer token (30-min TTL) if user/pass auth is used


def _auth_params() -> dict:
    """Prefer an API key; fall back to a username/password -> token exchange."""
    key = os.environ.get("IVOL_API_KEY")
    if key:
        return {"apiKey": key}
    user, pw = os.environ.get("IVOL_USER"), os.environ.get("IVOL_PASS")
    if user and pw:
        if _token[0] is None:
            _throttle()
            r = requests.get(BASE + EP_TOKEN, params={"username": user, "password": pw},
                             timeout=30)
            r.raise_for_status()
            _token[0] = r.text.strip().strip('"')
        return {"token": _token[0]}
    raise SystemExit(
        "No IVol credentials. Set IVOL_API_KEY (preferred) OR IVOL_USER + IVOL_PASS "
        "in .env once the 7-day trial issues them.")


def _throttle() -> None:
    with _lock:
        wait = _RATE_SECONDS - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _get(endpoint: str, params: dict) -> pd.DataFrame:
    _throttle()
    r = requests.get(BASE + endpoint, params={**_auth_params(), **params}, timeout=30)
    if r.status_code != 200:
        # 401/403 on IVol usually = endpoint not in your plan tier.
        raise RuntimeError(f"{endpoint} -> HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    rows = body.get("data", body) if isinstance(body, dict) else body
    df = pd.DataFrame(rows)
    if not df.empty:
        df.columns = [c.lower() for c in df.columns]
    return df


# --- public surface --------------------------------------------------------
def stock_ohlc(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Stock EOD -> [date, open, high, low, close, volume] (lowercased)."""
    df = _get(EP_STOCK_EOD, {"symbol": symbol, "from": start, "to": end})
    if not df.empty and "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    return df


def list_contracts(symbol: str, on_date: str, exp_from: str, exp_to: str,
                   strike_from=None, strike_to=None, right=None) -> pd.DataFrame:
    """option-series-on-date -> [optionsymbol, callput, strike, expirationdate,
    optionid] for contracts listed on `on_date`."""
    p = {"symbol": symbol, "date": on_date, "expFrom": exp_from, "expTo": exp_to}
    if strike_from is not None: p["strikeFrom"] = strike_from
    if strike_to is not None:   p["strikeTo"] = strike_to
    if right:                   p["callPut"] = right
    return _get(EP_OPT_SERIES, p)


def option_eod(option_id, start: str, end: str) -> pd.DataFrame:
    """Daily EOD for ONE contract by optionId. Columns (lowercased) include:
    date, price (mid mark), bid, ask, iv, delta, gamma, vega, theta,
    volume, 'open interest', 'unadjusted close'. No per-contract OHLC."""
    return _get(EP_OPT_EOD, {"optionId": option_id, "from": start, "to": end})


def _mark(df: pd.DataFrame) -> pd.Series:
    """The daily option mark our engine consumes as 'close': IVol's 'price'
    (settlement mid) when present, else the mid of bid/ask."""
    if "price" in df:
        return df["price"].astype(float)
    if "close" in df:
        return df["close"].astype(float)
    return (df["bid"].astype(float) + df["ask"].astype(float)) / 2.0


def resolve_option_id(symbol: str, expiration: str, strike: float, right: str,
                      on_date: str):
    """Return the integer optionId matching (strike, nearest expiration, right),
    looked up as listed on `on_date` (the entry date)."""
    exp = pd.Timestamp(str(expiration)[:10])
    lo, hi = round(float(strike) - 0.51, 2), round(float(strike) + 0.51, 2)
    c = list_contracts(symbol, on_date, (exp - pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
                       (exp + pd.Timedelta(days=5)).strftime("%Y-%m-%d"), lo, hi, right)
    if c.empty:
        return None
    c = c.copy()
    c["strike"] = c["strike"].astype(float)
    c = c.loc[(c["strike"] - float(strike)).abs() <= 0.01]
    if c.empty:
        return None
    c["expdiff"] = (pd.to_datetime(c["expirationdate"]) - exp).abs()
    row = c.sort_values("expdiff").iloc[0]
    return int(row["optionid"])


def option_series(symbol: str, expiration: str, strike: float, right: str,
                  start: str, end: str) -> pd.DataFrame:
    """Daily marks for ONE contract -> DataFrame[index=date, columns=['close']]
    (+ iv/delta/bid/ask/volume/oi kept for diagnostics). Exact shape the engine
    reads. right = 'P' | 'C'. Lookup is anchored on `start` (the entry date)."""
    oid = resolve_option_id(symbol, expiration, strike, right, start)
    if oid is None:
        return pd.DataFrame(columns=["close"])
    raw = option_eod(oid, start, end)
    if raw.empty:
        return pd.DataFrame(columns=["close"])
    raw["date"] = pd.to_datetime(raw["date"])
    out = raw.set_index("date").sort_index()
    out["close"] = _mark(out)
    keep = ["close"] + [c for c in ("iv", "delta", "bid", "ask", "volume",
                                    "open interest") if c in out.columns]
    return out[keep]


def iv_series(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Daily IV index (ivx) — Study 1 crown jewel."""
    df = _get(EP_IVX, {"symbol": symbol, "from": start, "to": end})
    if not df.empty and "date" in df:
        df["date"] = pd.to_datetime(df["date"])
    return df


def earnings(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Historical earnings dates (Studies 3 & 7)."""
    df = _get(EP_EARNINGS, {"symbol": symbol, "from": start, "to": end})
    return df


@dataclass
class ProbeResult:
    symbol: str
    stock_ok: bool
    chain_ok: bool
    per_contract_ohlc: bool     # does the option carry open/high/low?
    has_iv: bool
    has_greeks: bool
    has_oi: bool
    n_contracts: int
    note: str = ""
