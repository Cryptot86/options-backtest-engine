"""GLBX (CME) futures-options layer — plan-covered, $0 marginal cost.

Same architecture as the OPRA equity layer, adapted for futures:
  - signals run on the CONTINUOUS front-month series (e.g. CL.n.0)
  - options live under their own root (CL futures -> LO options)
  - each option's `underlying` names the exact futures contract (e.g. CLQ5);
    Black-76 prices off that future, not the continuous series
  - contract multipliers differ per product (CL = 1,000 bbl)

All pulls are cache-first via store.cached, schemas are L0 (ohlcv-1d,
definition) -> included in the CME Standard plan.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv

from ..data import store
from .blackscholes import b76_delta, b76_price, strike_for_delta

load_dotenv()

_GLBX = "GLBX.MDP3"
_local = threading.local()

# product specs: futures root -> options root, contract multiplier, and the
# option's tick value in $ per contract (slippage = 1 tick per side; a flat
# price-based slippage x multiplier wildly overcharges big-multiplier products)
FUT_SPECS = {
    "CL": {"opt_root": "LO", "mult": 1_000, "opt_tick_usd": 10.0},    # 0.01 $/bbl
    "NG": {"opt_root": "ON", "mult": 10_000, "opt_tick_usd": 10.0},   # 0.001 $/MMBtu
    "GC": {"opt_root": "OG", "mult": 100, "opt_tick_usd": 10.0},      # 0.10 $/oz
    "6E": {"opt_root": "EUU", "mult": 125_000, "opt_tick_usd": 12.5}, # 0.0001 $/EUR
    "6B": {"opt_root": "GBU", "mult": 62_500, "opt_tick_usd": 6.25},  # 0.0001 $/GBP
    # ES quarterlies live under root ES; the MONTHLY (EOM) series is root EW —
    # without EW the expiry calendar is quarterly-only and (e.g.) the entire
    # Feb-2020 crash window has no 30-75 DTE expiry -> crash signals silently
    # skipped (survivorship). Both roots merged for definitions.
    "ES": {"opt_root": ["ES", "EW"], "mult": 50, "opt_tick_usd": 12.5},  # 0.25 pt
    # ZB 30-yr T-bond (CBOT): options root OZB (serials+quarterlies), 1/64 tick
    "ZB": {"opt_root": "OZB", "mult": 1_000, "opt_tick_usd": 15.625},
    # RTY E-mini Russell 2000: quarterly options root RTO + EOM monthlies RTM
    "RTY": {"opt_root": ["RTO", "RTM"], "mult": 50, "opt_tick_usd": 5.0},
    # Treasury curve: 10yr note (most liquid) and 2yr note
    "ZN": {"opt_root": "OZN", "mult": 1_000, "opt_tick_usd": 15.625},
    "ZT": {"opt_root": "OZT", "mult": 2_000, "opt_tick_usd": 15.625},
    # Silver (COMEX): options root SO, 5000 oz, $0.005 tick = $25
    "SI": {"opt_root": "SO", "mult": 5_000, "opt_tick_usd": 25.0},
    # Grains (CBOT): 5000 bu, quoted cents/bu -> $50 per point(cent); tick 1/8c=$6.25
    "ZC": {"opt_root": "OZC", "mult": 50, "opt_tick_usd": 6.25},
    "ZW": {"opt_root": "OZW", "mult": 50, "opt_tick_usd": 6.25},
    "ZS": {"opt_root": "OZS", "mult": 50, "opt_tick_usd": 6.25},
    # NQ: quarterlies root NQ + end-of-month QNE (same survivorship fix as ES/EW)
    "NQ": {"opt_root": ["NQ", "QNE"], "mult": 20, "opt_tick_usd": 5.0},
    # Copper (COMEX): options root HX
    "HG": {"opt_root": "HXE", "mult": 25_000, "opt_tick_usd": 12.5},
}


def client():
    c = getattr(_local, "client", None)
    if c is None:
        import databento as db
        c = db.Historical(os.environ["DATABENTO_API_KEY"])
        _local.client = c
    return c


# ---------------------------------------------------------------------------
# Fetchers (all cache-first, all L0/plan-covered)
# ---------------------------------------------------------------------------
def get_continuous(root: str, start, end) -> pd.DataFrame:
    """Front-month continuous daily OHLCV (volume-ranked, e.g. CL.n.0)."""
    key = ("glbx", "cont", f"{root}__{start}__{end}.parquet")

    def _fetch():
        df = client().timeseries.get_range(
            dataset=_GLBX, symbols=[f"{root}.n.0"], stype_in="continuous",
            schema="ohlcv-1d", start=str(start), end=str(end)).to_df()
        if df.empty:
            return df
        out = df.reset_index()
        out["date"] = pd.to_datetime(out["ts_event"]).dt.tz_localize(None).dt.normalize()
        return out[["date", "open", "high", "low", "close", "volume"]]

    df = store.cached(key, _fetch)
    if "__empty__" in df.columns or df.empty:
        return pd.DataFrame()
    return df.set_index("date").sort_index()


def get_option_definitions(fut_root: str, day) -> pd.DataFrame:
    """Listed options (strikes/expiries/underlying) for one day.

    opt_root may be a list (e.g. ES quarterlies + EW monthlies) — each root is
    fetched/cached separately and the frames merged.
    """
    roots = FUT_SPECS[fut_root]["opt_root"]
    if isinstance(roots, str):
        roots = [roots]
    day = pd.Timestamp(day).normalize()
    frames = []
    for opt_root in roots:
        key = ("glbx", "definition", opt_root, day.strftime("%Y-%m-%d") + ".parquet")

        def _fetch(opt_root=opt_root):
            s = day.strftime("%Y-%m-%d")
            e = (day + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            df = client().timeseries.get_range(
                dataset=_GLBX, symbols=[f"{opt_root}.OPT"], stype_in="parent",
                schema="definition", start=s, end=e).to_df()
            if df.empty:
                return df
            cols = ["raw_symbol", "instrument_class", "strike_price", "expiration",
                    "underlying"]
            df = df[[c for c in cols if c in df.columns]].drop_duplicates("raw_symbol")
            df["expiration"] = pd.to_datetime(df["expiration"]).dt.tz_localize(None)
            return df.reset_index(drop=True)

        df = store.cached(key, _fetch)
        if "__empty__" not in df.columns and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates("raw_symbol")


def get_symbol_settlements(raw_symbol: str, start, end) -> pd.DataFrame:
    """Official daily SETTLEMENT prices for one instrument -> [date, mid].

    CME settles every listed strike daily even when it never trades, so this
    covers the sparse OTM options that ohlcv-1d (last trade) misses. Source:
    statistics schema (L0, plan-covered), stat_type 3 = settlement price.
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    key = ("glbx", "settle", f"{raw_symbol}__{start:%Y-%m-%d}__{end:%Y-%m-%d}.parquet")

    def _fetch():
        s = start.strftime("%Y-%m-%d")
        e = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = client().timeseries.get_range(
            dataset=_GLBX, symbols=[raw_symbol], stype_in="raw_symbol",
            schema="statistics", start=s, end=e).to_df()
        if df.empty:
            return df
        df = df.reset_index()
        df = df[df["stat_type"] == 3]                  # settlement price
        df = df[pd.notna(df["price"]) & (df["price"] > 0)]
        if df.empty:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["ts_ref" if "ts_ref" in df else "ts_event"]) \
            .dt.tz_localize(None).dt.normalize()
        df = df.rename(columns={"price": "mid"})
        return df.groupby("date", as_index=False)["mid"].last()

    df = store.cached(key, _fetch)
    return df if "__empty__" not in df.columns else pd.DataFrame()


def get_option_path(raw_symbol: str, start, end) -> pd.DataFrame:
    """Best daily price path for an option: settlements first (complete),
    last-trade bars as fallback."""
    p = get_symbol_settlements(raw_symbol, start, end)
    if not p.empty:
        return p
    return get_symbol_daily(raw_symbol, start, end)


def get_symbol_daily(raw_symbol: str, start, end) -> pd.DataFrame:
    """Daily closes for one GLBX instrument (option or future) -> [date, mid]."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    key = ("glbx", "daily", f"{raw_symbol}__{start:%Y-%m-%d}__{end:%Y-%m-%d}.parquet")

    def _fetch():
        s = start.strftime("%Y-%m-%d")
        e = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        df = client().timeseries.get_range(
            dataset=_GLBX, symbols=[raw_symbol], stype_in="raw_symbol",
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
# 16-delta put selection (model-picked, Black-76)
# ---------------------------------------------------------------------------
@dataclass
class SelectedFutOption:
    raw_symbol: str
    underlying: str          # futures contract, e.g. CLQ5
    strike: float
    expiration: pd.Timestamp
    dte: int
    fut_price: float         # underlying future's price at entry
    price: float             # filled from real path entry mark
    iv: float
    delta: float


def select_16d_fut(fut_root: str, entry_date, iv_estimate,
                   dte_min=30, dte_max=45, dte_target=40,
                   target_delta=0.16) -> SelectedFutOption | None:
    """Back-compat wrapper: 16-delta put."""
    return select_delta_option(fut_root, entry_date, iv_estimate, kind="put",
                               target_delta=target_delta, dte_min=dte_min,
                               dte_max=dte_max, dte_target=dte_target)


def select_delta_option(fut_root: str, entry_date, iv_estimate, kind="put",
                        target_delta=0.16, dte_min=30, dte_max=45,
                        dte_target=40) -> SelectedFutOption | None:
    """Pick a put OR call at any target delta on the futures option chain.

    Picks the expiry nearest dte_target (with the monthly fallback rule),
    reads the option's `underlying` futures contract, pulls THAT future's
    entry price (plan-covered), and solves the Black-76 strike -> snap to
    listed. Used for single legs and multi-leg structures alike.
    """
    entry_date = pd.Timestamp(entry_date).normalize()
    defs = get_option_definitions(fut_root, entry_date)
    if defs.empty:
        return None
    cls = "P" if kind == "put" else "C"
    puts = defs[defs["instrument_class"] == cls].copy()
    if puts.empty:
        return None
    puts["dte"] = (puts["expiration"].dt.normalize() - entry_date).dt.days
    window = puts[(puts["dte"] >= dte_min) & (puts["dte"] <= dte_max)]
    if window.empty:
        # Futures options are monthly: often NO expiry sits in 30-45 DTE.
        # TJ's rule: fall back to the nearest expiry with DTE >= 40 (never a
        # shorter-dated one), capped at 75 to stay out of far months.
        window = puts[(puts["dte"] >= max(dte_min, 40)) & (puts["dte"] <= 75)]
        if window.empty:
            return None
    puts = window
    exp = puts.iloc[(puts["dte"] - dte_target).abs().argsort().iloc[0]]["dte"]
    puts = puts[puts["dte"] == exp]

    und = str(puts.iloc[0]["underlying"])          # e.g. CLQ5
    fpx = get_symbol_daily(und, entry_date, entry_date)
    if fpx.empty:
        return None
    F = float(fpx.iloc[0]["mid"])

    T = int(exp) / 365.0
    if iv_estimate is None or pd.isna(iv_estimate):   # unwarmed rvol -> sane default
        iv_estimate = 0.30
    # Floor only guards degenerate values. A 0.10 floor overshot low-vol FX
    # (euro ~8% vol -> strikes landed ~10-delta instead of 16).
    iv_use = max(iv_estimate * 1.15, 0.03)
    K_star = strike_for_delta(F, T, iv_use, target_delta, kind=kind, futures=True)
    r = puts.iloc[(puts["strike_price"] - K_star).abs().argsort().iloc[0]]
    return SelectedFutOption(str(r["raw_symbol"]), und, float(r["strike_price"]),
                             pd.Timestamp(r["expiration"]).normalize(), int(r["dte"]),
                             F, float("nan"), float("nan"), float("nan"))


# ---------------------------------------------------------------------------
# Trade simulation (Black-76, product multiplier)
# ---------------------------------------------------------------------------
from ..config import TRADE, COST


@dataclass
class FutTradeResult:
    symbol: str
    signal_type: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    strike: float
    dte: int
    entry_iv: float
    entry_delta: float
    entry_credit: float
    pnl: float
    pnl_pct_credit: float
    mae: float
    days_held: int
    exit_reason: str


def simulate_fut_trade(fut_root, entry_date, cont_df, signal_type, iv_proxy,
                       invalidation_below_ema100=False, stop_loss_dollars=None,
                       kind="put", trade=TRADE) -> FutTradeResult | None:
    """Simulate one short futures-option trade off real GLBX daily prices.

    kind='put' (default) or 'call' (H10 call side, downtrends). For calls the
    thesis-invalidation flips: close back ABOVE the 100-EMA exits.
    cont_df is the prepped continuous frame (close/ema100 columns) used for the
    trading calendar and the invalidation rule.
    """
    mult = FUT_SPECS[fut_root]["mult"]
    entry_date = pd.Timestamp(entry_date).normalize()
    if entry_date not in cont_df.index:
        return None

    sel = select_delta_option(fut_root, entry_date, iv_proxy, kind=kind,
                              dte_min=trade.dte_min, dte_max=trade.dte_max,
                              dte_target=trade.dte_target,
                              target_delta=trade.target_delta)
    if sel is None:
        return None

    path = get_option_path(sel.raw_symbol, entry_date, sel.expiration)
    if path.empty:
        return None
    path = path.set_index("date").sort_index()
    if entry_date not in path.index:
        return None
    entry_price = float(path.loc[entry_date, "mid"])
    if entry_price <= 0:
        return None

    # real IV/delta implied from the entry mark via Black-76
    from scipy.optimize import brentq
    T = sel.dte / 365.0
    try:
        entry_iv = brentq(lambda s: b76_price(sel.fut_price, sel.strike, T, s,
                                              kind=kind) - entry_price,
                          1e-3, 5.0, maxiter=100)
        entry_delta = b76_delta(sel.fut_price, sel.strike, T, entry_iv, kind=kind)
    except (ValueError, RuntimeError):
        entry_iv = entry_delta = float("nan")

    gross_credit = entry_price * mult
    fees = (COST.commission_per_contract + COST.exchange_fees_per_contract)
    slip = FUT_SPECS[fut_root].get("opt_tick_usd", 10.0)   # 1 option tick per side
    tp_price = entry_price * (1 - trade.take_profit_pct)

    # underlying futures path for expiration intrinsic
    days = cont_df.loc[entry_date:sel.expiration].index
    last_opt = entry_price
    worst_pnl = 0.0
    exit_reason, exit_date, exit_opt = "expiration", days[-1], None

    for dt in days[1:]:
        if dt in path.index:
            last_opt = float(path.loc[dt, "mid"])
        opt = last_opt
        dte = (sel.expiration - dt).days
        cur_pnl = (entry_price - opt) * mult
        worst_pnl = min(worst_pnl, cur_pnl)

        if opt <= tp_price:
            exit_reason, exit_date, exit_opt = "take_profit_50", dt, tp_price
            break
        if stop_loss_dollars is not None and cur_pnl <= -abs(stop_loss_dollars):
            exit_reason, exit_date, exit_opt = "stop_loss", dt, opt
            break
        if invalidation_below_ema100:
            c, e = float(cont_df.loc[dt, "close"]), float(cont_df.loc[dt, "ema100"])
            # short put (uptrend thesis): close BELOW ema100 invalidates;
            # short call (downtrend thesis): close ABOVE ema100 invalidates.
            if (kind == "put" and c < e) or (kind == "call" and c > e):
                exit_reason, exit_date, exit_opt = "ema100_invalidation", dt, opt
                break
        if dte <= trade.manage_dte:
            exit_reason, exit_date, exit_opt = "manage_21dte", dt, opt
            break

    if exit_opt is None:   # expiration -> intrinsic on the underlying future
        fend = get_symbol_daily(sel.underlying, exit_date, exit_date)
        Fx = float(fend.iloc[0]["mid"]) if not fend.empty else float(cont_df.loc[exit_date, "close"])
        exit_opt = max(sel.strike - Fx, 0.0) if kind == "put" else max(Fx - sel.strike, 0.0)

    pnl = gross_credit - exit_opt * mult - 2 * slip - 2 * fees
    return FutTradeResult(
        symbol=fut_root, signal_type=signal_type, entry_date=entry_date,
        exit_date=pd.Timestamp(exit_date), strike=sel.strike, dte=sel.dte,
        entry_iv=entry_iv, entry_delta=entry_delta,
        entry_credit=gross_credit - slip - fees, pnl=pnl,
        pnl_pct_credit=pnl / gross_credit if gross_credit else 0.0,
        mae=worst_pnl, days_held=(pd.Timestamp(exit_date) - entry_date).days,
        exit_reason=exit_reason,
    )


# ---------------------------------------------------------------------------
# Multi-leg structures (Strategy Lab)
# ---------------------------------------------------------------------------
# legs: (kind, target_delta, side)  side -1 = sell, +1 = buy
STRUCTURES = {
    "short_put":         [("put", 0.16, -1)],
    "short_strangle":    [("put", 0.16, -1), ("call", 0.16, -1)],
    "iron_butterfly":    [("put", 0.50, -1), ("call", 0.50, -1),
                          ("put", 0.10, +1), ("call", 0.10, +1)],
    "put_credit_spread": [("put", 0.16, -1), ("put", 0.08, +1)],
    "crisis_fade_spread": [("put", 0.25, -1), ("put", 0.05, +1)],
}


def simulate_structure(fut_root, entry_date, cont_df, structure, iv_proxy,
                       signal_type="lab", trade=TRADE) -> FutTradeResult | None:
    """Simulate a multi-leg premium structure off real settlement paths.

    Position value V_t = sum(side_i * leg_price_i). P&L_t = (V_0 - V_t) * mult
    for a net-short (credit) structure. Managed at 50% of net credit / 21 DTE.
    Every leg's path is a plan-covered settlement pull (cached forever).
    """
    mult = FUT_SPECS[fut_root]["mult"]
    tick = FUT_SPECS[fut_root].get("opt_tick_usd", 10.0)
    entry_date = pd.Timestamp(entry_date).normalize()
    if entry_date not in cont_df.index:
        return None

    legs = []
    for kind, tgt, side in STRUCTURES[structure]:
        sel = select_delta_option(fut_root, entry_date, iv_proxy, kind=kind,
                                  target_delta=tgt, dte_min=trade.dte_min,
                                  dte_max=trade.dte_max, dte_target=trade.dte_target)
        if sel is None:
            return None
        p = get_option_path(sel.raw_symbol, entry_date, sel.expiration)
        if p.empty:
            return None
        p = p.set_index("date")["mid"].sort_index()
        if entry_date not in p.index or p.loc[entry_date] <= 0:
            return None
        legs.append((sel, p, side, kind))

    expiration = legs[0][0].expiration            # all legs same expiry
    n_legs = len(legs)
    fees = (COST.commission_per_contract + COST.exchange_fees_per_contract) * n_legs
    slip = tick * n_legs                          # 1 tick per leg per side

    def value_on(dt, last_vals):
        v = 0.0
        for i, (sel, p, side, kind) in enumerate(legs):
            if dt in p.index:
                last_vals[i] = float(p.loc[dt])
            v += side * last_vals[i]
        return v

    last_vals = [float(p.loc[entry_date]) for (_, p, _, _) in legs]
    v0 = sum(side * lv for (_, _, side, _), lv in zip(legs, last_vals))
    net_credit = -v0 * mult                        # positive for net-short
    if net_credit <= 0:
        return None                                # only test credit structures
    tp_pnl = trade.take_profit_pct * net_credit

    days = cont_df.loc[entry_date:expiration].index
    worst_pnl = 0.0
    exit_reason, exit_date, exit_v = "expiration", days[-1], None
    for dt in days[1:]:
        v = value_on(dt, last_vals)
        cur_pnl = (v0 - v) * mult                  # short credit: value down = profit
        worst_pnl = min(worst_pnl, cur_pnl)
        dte = (expiration - dt).days
        if cur_pnl >= tp_pnl:
            exit_reason, exit_date, exit_v = "take_profit_50", dt, v
            break
        if dte <= trade.manage_dte:
            exit_reason, exit_date, exit_v = "manage_21dte", dt, v
            break

    if exit_v is None:                             # expiration -> intrinsic per leg
        und = legs[0][0].underlying
        fend = get_symbol_daily(und, exit_date, exit_date)
        Fx = float(fend.iloc[0]["mid"]) if not fend.empty else float(cont_df.loc[exit_date, "close"])
        exit_v = 0.0
        for sel, _, side, kind in legs:
            intr = max(sel.strike - Fx, 0.0) if kind == "put" else max(Fx - sel.strike, 0.0)
            exit_v += side * intr

    pnl = (v0 - exit_v) * mult - 2 * slip - 2 * fees
    lead = legs[0][0]
    return FutTradeResult(
        symbol=fut_root, signal_type=signal_type, entry_date=entry_date,
        exit_date=pd.Timestamp(exit_date), strike=lead.strike, dte=lead.dte,
        entry_iv=float("nan"), entry_delta=float("nan"),
        entry_credit=net_credit - slip - fees, pnl=pnl,
        pnl_pct_credit=pnl / net_credit, mae=worst_pnl,
        days_held=(pd.Timestamp(exit_date) - entry_date).days,
        exit_reason=exit_reason,
    )
