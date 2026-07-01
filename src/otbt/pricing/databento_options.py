"""Layer 2 — real-IV option data from Databento (OPRA equities), cache-first.

Approach B (cost-minimized, ~$53 for the full equity universe, then $0 on
re-runs thanks to the local store):

  1. definition (cheap) -> listed put strikes/expiries for symbol/day  [cached]
  2. pick the target expiry (30-45 DTE) and a candidate 16-delta strike using
     an IV estimate (realized-vol proxy)
  3. pull ONLY that instrument + a few neighbors' EOD close             [cached]
     imply IV from the real price, choose the true 16-delta put
  4. pull that one instrument's daily closes over the holding window    [cached]
     to drive the 50%/21DTE management rules

Every timeseries.get_range call (the billed ones) goes through store.cached().
get_cost()/get_billable_size() are free and used only for projection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv

from ..data import store
from .blackscholes import bs_delta, bs_price, strike_for_delta

load_dotenv()

_OPRA = "OPRA.PILLAR"
_client = None


def client():
    global _client
    if _client is None:
        import databento as db
        _client = db.Historical(os.environ["DATABENTO_API_KEY"])
    return _client


def _day_range(d):
    d = pd.Timestamp(d).normalize()
    return d.strftime("%Y-%m-%d"), (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Cost projection (free metadata)
# ---------------------------------------------------------------------------
def cost_for(symbol, day, schema) -> float:
    s, e = _day_range(day)
    return float(client().metadata.get_cost(
        dataset=_OPRA, symbols=[f"{symbol}.OPT"], stype_in="parent",
        schema=schema, start=s, end=e))


# ---------------------------------------------------------------------------
# Billed fetches (all cache-first via store.cached)
# ---------------------------------------------------------------------------
def get_definitions(symbol, day) -> pd.DataFrame:
    day = pd.Timestamp(day).normalize()
    key = ("opra", "definition", symbol, day.strftime("%Y-%m-%d") + ".parquet")

    def _fetch():
        s, e = _day_range(day)
        df = client().timeseries.get_range(
            dataset=_OPRA, symbols=[f"{symbol}.OPT"], stype_in="parent",
            schema="definition", start=s, end=e).to_df()
        if df.empty:
            return df
        cols = ["instrument_id", "raw_symbol", "instrument_class",
                "strike_price", "expiration"]
        df = df[[c for c in cols if c in df.columns]].drop_duplicates("instrument_id")
        df["expiration"] = pd.to_datetime(df["expiration"]).dt.tz_localize(None)
        return df.reset_index(drop=True)

    df = store.cached(key, _fetch)
    return df if "__empty__" not in df.columns else pd.DataFrame()


def get_symbol_path(raw_symbol, start, end) -> pd.DataFrame:
    """Daily closes for a single option, keyed by its stable OSI raw_symbol.

    OPRA numeric instrument_ids are recycled across days, so multi-day tracking
    MUST use raw_symbol (stype_in='raw_symbol'), not instrument_id.
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    key = ("opra", "sym",
           f"{raw_symbol}__{start:%Y-%m-%d}__{end:%Y-%m-%d}.parquet")

    def _fetch():
        s = start.strftime("%Y-%m-%d")
        e = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = client().timeseries.get_range(
            dataset=_OPRA, symbols=[raw_symbol], stype_in="raw_symbol",
            schema="ohlcv-1d", start=s, end=e).to_df()
        if df.empty:
            return df
        out = df.reset_index()[["ts_event", "close"]]
        out["date"] = pd.to_datetime(out["ts_event"]).dt.tz_localize(None).dt.normalize()
        # one bar per day; guard against any dupes
        return out.groupby("date", as_index=False)["close"].last()

    df = store.cached(key, _fetch)
    return df if "__empty__" not in df.columns else pd.DataFrame()


def _symbol_close_on(raw_symbol, day) -> float | None:
    p = get_symbol_path(raw_symbol, day, day)
    if p.empty:
        return None
    return float(p.iloc[0]["close"])


# ---------------------------------------------------------------------------
# 16-delta put selection (Approach B)
# ---------------------------------------------------------------------------
@dataclass
class SelectedOption:
    instrument_id: int
    raw_symbol: str
    strike: float
    expiration: pd.Timestamp
    dte: int
    price: float
    iv: float
    delta: float


def select_16delta_put(symbol, entry_date, underlying_px, iv_estimate,
                       dte_min=30, dte_max=45, dte_target=40,
                       target_delta=0.16, neighbors=3) -> SelectedOption | None:
    """Select the true 16-delta put with minimal billed pulls.

    Uses iv_estimate (realized-vol proxy) only to locate a candidate strike;
    the final choice is made from REAL prices of the candidate + neighbors.
    """
    defs = get_definitions(symbol, entry_date)
    if defs.empty:
        return None
    puts = defs[defs["instrument_class"] == "P"].copy()
    if puts.empty:
        return None
    puts["dte"] = (puts["expiration"] - pd.Timestamp(entry_date)).dt.days
    puts = puts[(puts["dte"] >= dte_min) & (puts["dte"] <= dte_max)]
    if puts.empty:
        return None
    # target the expiry closest to dte_target
    exp = puts.iloc[(puts["dte"] - dte_target).abs().argsort().iloc[0]]["dte"]
    puts = puts[puts["dte"] == exp].sort_values("strike_price").reset_index(drop=True)

    T = int(exp) / 365.0

    def _eval(row) -> SelectedOption | None:
        """Pull one strike's real EOD price and imply IV/delta; reject stale
        prints (absurd implied vol) so a thin last-trade can't poison selection."""
        from scipy.optimize import brentq
        px = _symbol_close_on(str(row["raw_symbol"]), entry_date)
        if px is None or px <= 0:
            return None
        K = float(row["strike_price"])
        try:
            iv = brentq(lambda s: bs_price(underlying_px, K, T, s, kind="put") - px,
                        1e-3, 5.0, maxiter=100)
        except (ValueError, RuntimeError):
            return None
        if not (0.03 <= iv <= 2.0):          # stale/garbage mark
            return None
        d = bs_delta(underlying_px, K, T, iv, kind="put")
        return SelectedOption(int(row["instrument_id"]), str(row["raw_symbol"]), K,
                              pd.Timestamp(row["expiration"]), int(row["dte"]),
                              px, iv, d)

    # --- pass 1: seed real IV from the liquid ATM put (nearest spot) ---
    iv_seed = None
    atm_order = (puts["strike_price"] - underlying_px).abs().argsort()
    for j in atm_order.iloc[:4]:              # try up to 4 nearest-ATM strikes
        s = _eval(puts.iloc[j])
        if s is not None:
            iv_seed = s.iv
            break
    iv_use = iv_seed if iv_seed is not None else max(iv_estimate, 0.05)

    # --- pass 2: center the 16-delta search on the REAL-IV strike ---
    K_star = strike_for_delta(underlying_px, T, iv_use, target_delta, kind="put")
    ci = (puts["strike_price"] - K_star).abs().argsort().iloc[0]
    lo, hi = max(0, ci - neighbors), min(len(puts), ci + neighbors + 1)

    best = None
    for _, r in puts.iloc[lo:hi].iterrows():
        cand = _eval(r)
        if cand is None:
            continue
        if best is None or abs(abs(cand.delta) - target_delta) < abs(abs(best.delta) - target_delta):
            best = cand
    return best
