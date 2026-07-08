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
import threading
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv

from ..data import store
from .blackscholes import bs_delta, bs_price, strike_for_delta

load_dotenv()

_OPRA = "OPRA.PILLAR"
_local = threading.local()


def client():
    """Thread-local Databento client so concurrent workers don't share state."""
    c = getattr(_local, "client", None)
    if c is None:
        import databento as db
        c = db.Historical(os.environ["DATABENTO_API_KEY"])
        _local.client = c
    return c


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


def get_symbol_quotes(raw_symbol, start, end) -> pd.DataFrame:
    """EOD bid/ask MID per day for a single option (schema cbbo-1m).

    Uses the closing quote mid (not last trade) so the implied-vol smile is
    clean and 16-delta selection is stable. Returns columns [date, mid].

    OPRA numeric instrument_ids are recycled across days, so multi-day tracking
    MUST use raw_symbol (stype_in='raw_symbol'), not instrument_id.
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    key = ("opra", "quote",
           f"{raw_symbol}__{start:%Y-%m-%d}__{end:%Y-%m-%d}.parquet")

    def _fetch():
        s = start.strftime("%Y-%m-%d")
        e = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = client().timeseries.get_range(
            dataset=_OPRA, symbols=[raw_symbol], stype_in="raw_symbol",
            schema="cbbo-1m", start=s, end=e).to_df()
        if df.empty:
            return df
        df = df.reset_index()
        bid, ask = df["bid_px_00"].astype(float), df["ask_px_00"].astype(float)
        df = df.assign(bid=bid, ask=ask)
        df = df[(df["bid"] > 0) & (df["ask"] > 0)]        # valid two-sided quotes only
        if df.empty:
            return pd.DataFrame()
        # closing quote: last valid 1-min bar at/under 16:00 ET each trading day
        et = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert("America/New_York")
        df = df.assign(date=et.dt.normalize().dt.tz_localize(None),
                       mins=et.dt.hour * 60 + et.dt.minute)   # minute-of-day ET
        df = df[df["mins"] <= 16 * 60]              # at/under 16:00 ET close
        if df.empty:
            return pd.DataFrame()
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
        # closing quote = last valid bar of each trading day
        return (df.sort_values(["date", "mins"]).groupby("date", as_index=False)["mid"].last())

    df = store.cached(key, _fetch)
    return df if "__empty__" not in df.columns else pd.DataFrame()


def _symbol_mid_on(raw_symbol, day) -> float | None:
    p = get_symbol_quotes(raw_symbol, day, day)
    if p.empty:
        return None
    return float(p.iloc[0]["mid"])


def get_symbol_daily(raw_symbol, start, end) -> pd.DataFrame:
    """Daily last-trade closes for one option (schema ohlcv-1d) -> [date, mid].

    ~400x less data than cbbo-1m minute bars (1 bar/day vs ~390), so it's the
    fast/cheap default for the option's price path. Marks are last-trade (vs
    quote-mid); fine for a liquid model-picked 16-delta strike where credits are
    treated as approximate.
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    key = ("opra", "daily", f"{raw_symbol}__{start:%Y-%m-%d}__{end:%Y-%m-%d}.parquet")

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
        out = out.rename(columns={"close": "mid"})
        return out.groupby("date", as_index=False)["mid"].last()

    df = store.cached(key, _fetch)
    return df if "__empty__" not in df.columns else pd.DataFrame()


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


def select_16d_modeled(symbol, entry_date, spot, iv_estimate,
                       dte_min=30, dte_max=45, dte_target=40,
                       target_delta=0.16, kind="put") -> SelectedOption | None:
    """Pick a target-delta option (put OR call) WITHOUT any quote pulls.

    Uses only the (cheap, cached) definitions to know listed strikes/expiries,
    then places the strike with the MODEL (proven within ~1 strike of the real
    16-delta). No per-strike quote requests -> the only paid pull per trade is
    the one chosen option's price path. price/iv/delta are filled later from the
    real path's entry-day mark.
    """
    defs = get_definitions(symbol, entry_date)
    if defs.empty:
        return None
    cls = "P" if kind == "put" else "C"
    puts = defs[defs["instrument_class"] == cls].copy()
    if puts.empty:
        return None
    puts["dte"] = (puts["expiration"] - pd.Timestamp(entry_date)).dt.days
    puts = puts[(puts["dte"] >= dte_min) & (puts["dte"] <= dte_max)]
    if puts.empty:
        return None
    exp = puts.iloc[(puts["dte"] - dte_target).abs().argsort().iloc[0]]["dte"]
    puts = puts[puts["dte"] == exp]
    # SPLIT-SCALE GUARD: caller's spot is split-ADJUSTED (yfinance) but listed
    # strikes are RAW. Pre-split eras (GOOGL/AMZN 20:1, NVDA 40x cum, AAPL/TSLA)
    # would otherwise snap to the wrong strike entirely. Infer the scale from
    # the strike ladder's median vs spot and place the strike on the RAW scale.
    med = float(puts["strike_price"].median())
    scale = 1.0
    if spot > 0 and (med / spot > 1.6 or med / spot < 0.625):
        for f in (2, 3, 4, 5, 10, 15, 20, 40):
            if 0.625 <= med / (spot * f) <= 1.6:
                scale = float(f); break
        else:
            return None                      # unrecognizable ladder — refuse, don't guess
    T = int(exp) / 365.0
    iv_use = max(iv_estimate * 1.15, 0.06)         # VRP bump toward real IV
    K_star = strike_for_delta(spot * scale, T, iv_use, target_delta, kind=kind)
    r = puts.iloc[(puts["strike_price"] - K_star).abs().argsort().iloc[0]]  # snap to listed
    sel = SelectedOption(int(r["instrument_id"]), str(r["raw_symbol"]),
                          float(r["strike_price"]), pd.Timestamp(r["expiration"]),
                          int(r["dte"]), price=float("nan"), iv=float("nan"),
                          delta=float("nan"))
    sel.scale = scale        # raw-per-adjusted factor; divide strike/premiums by this
    return sel


def select_16delta_put(symbol, entry_date, underlying_px, iv_estimate,
                       dte_min=30, dte_max=45, dte_target=40,
                       target_delta=0.16, band=(0.10, 0.25)) -> SelectedOption | None:
    """Select the target-delta put by pulling ONLY the sell-zone delta band.

    We only ever sell in the ~15-20 delta region, so we pull real quotes only
    for strikes whose theoretical delta (at a VRP-bumped proxy IV) falls in
    `band` (default 0.10-0.25 = 15-20 delta plus a small buffer to guarantee we
    bracket 16 delta even when the proxy is off). Final pick = the strike whose
    REAL-quote-implied delta is closest to target_delta.
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
        px = _symbol_mid_on(str(row["raw_symbol"]), entry_date)
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

    # Locate the sell-zone using theoretical deltas at a VRP-bumped proxy IV
    # (real IV > realized vol, so bump up ~15% and floor to avoid under-OTM).
    iv_use = max(iv_estimate * 1.15, 0.06)
    puts["th_delta"] = puts["strike_price"].apply(
        lambda K: abs(bs_delta(underlying_px, float(K), T, iv_use, kind="put")))
    zone = puts[(puts["th_delta"] >= band[0]) & (puts["th_delta"] <= band[1])]
    if zone.empty:                            # fallback: 5 nearest to target delta
        order = (puts["th_delta"] - target_delta).abs().argsort()
        zone = puts.iloc[order.iloc[:5]]

    # Pull real quotes only for the band; pick closest real delta to target.
    best = None
    for _, r in zone.iterrows():
        cand = _eval(r)
        if cand is None:
            continue
        if best is None or abs(abs(cand.delta) - target_delta) < abs(abs(best.delta) - target_delta):
            best = cand
    return best
