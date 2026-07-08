"""Sinclair factor-sorted straddles (D/E, RoE, RoA) with point-in-time EDGAR
fundamentals. LONG ATM straddles on HIGH-factor quartile, SHORT on LOW quartile.
Rebalance first trading day each month 2021-01..2026-05, hold 5 trading days.
Straddles priced ONCE per (name, rebalance date) and reused across all 3 factors.
Usage: python run_factor_edgar.py [--rank-only]
"""
from dotenv import load_dotenv; load_dotenv()
import json, os, sys, time, urllib.request
from datetime import datetime, timezone, date, timedelta
import numpy as np
import pandas as pd
from src.otbt.data.prices import get_prices
from src.otbt.data import db
from src.otbt.reporting.metrics import summarize
from src.otbt.pricing import databento_options as dbo

UNIVERSE = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD",
            "NFLX","AVGO","JPM","COST","LLY","UNH","HD"]
EDGAR_DIR = "data_cache/edgar"
HDR = {"User-Agent": "TJ Research vjm_tamil@yahoo.com"}
FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

# ---------------------------------------------------------------- EDGAR fetch
def _get_json(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def ensure_edgar():
    os.makedirs(EDGAR_DIR, exist_ok=True)
    tick_path = os.path.join(EDGAR_DIR, "company_tickers.json")
    if not os.path.exists(tick_path):
        data = _get_json("https://www.sec.gov/files/company_tickers.json")
        json.dump(data, open(tick_path, "w")); time.sleep(0.15)
    ticks = json.load(open(tick_path))
    cik = {v["ticker"]: int(v["cik_str"]) for v in ticks.values()}
    out = {}
    for t in UNIVERSE:
        p = os.path.join(EDGAR_DIR, f"{t}.json")
        if not os.path.exists(p):
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t]:010d}.json"
            print(f"EDGAR fetch {t} (CIK {cik[t]})", flush=True)
            json.dump(_get_json(url), open(p, "w")); time.sleep(0.15)
        out[t] = json.load(open(p))
    return out

# ------------------------------------------------------------- fact parsing
def _facts(cf, tag):
    try:
        units = cf["facts"]["us-gaap"][tag]["units"]["USD"]
    except KeyError:
        return []
    rows = []
    for u in units:
        if u.get("form") not in FORMS or "filed" not in u or u.get("val") is None:
            continue
        r = {"end": pd.Timestamp(u["end"]), "filed": pd.Timestamp(u["filed"]),
             "val": float(u["val"])}
        if "start" in u:
            r["start"] = pd.Timestamp(u["start"])
            r["dur"] = (r["end"] - r["start"]).days
        rows.append(r)
    return rows

def latest_instant(facts, asof):
    """Latest-period value knowable at `asof` (filed<=asof; max end, then max filed)."""
    fs = [f for f in facts if f["filed"] <= asof]
    if not fs:
        return None, None
    E = max(f["end"] for f in fs)
    best = max((f for f in fs if f["end"] == E), key=lambda f: f["filed"])
    return best["val"], E

def instant_at(facts, asof, end):
    fs = [f for f in facts if f["filed"] <= asof and f["end"] == end]
    if not fs:
        return None
    return max(fs, key=lambda f: f["filed"])["val"]

def ttm_ni(facts, asof):
    """Trailing-4Q net income knowable at `asof` (annual, or YTD + prevFY - prevYTD)."""
    fs = [f for f in facts if f["filed"] <= asof and "dur" in f]
    if not fs:
        return None
    E = max(f["end"] for f in fs)
    ann = [f for f in fs if f["end"] == E and 340 <= f["dur"] <= 380]
    if ann:
        return max(ann, key=lambda f: f["filed"])["val"]
    ytds = [f for f in fs if f["end"] == E and f["dur"] < 340]
    if not ytds:
        return None
    ytd = max(ytds, key=lambda f: (f["dur"], f["filed"]))
    # previous fiscal-year annual ending right before the YTD start
    pann = [f for f in fs if 340 <= f["dur"] <= 380
            and abs((f["end"] - (ytd["start"] - pd.Timedelta(days=1))).days) <= 10]
    if not pann:
        return None
    pann_v = max(pann, key=lambda f: f["filed"])["val"]
    # prior-year YTD of matching duration ending ~1yr before E
    tgt = E - pd.Timedelta(days=365)
    pytd = [f for f in fs if abs(f["dur"] - ytd["dur"]) <= 15
            and abs((f["end"] - tgt).days) <= 15]
    if not pytd:
        return None
    pytd_v = max(pytd, key=lambda f: f["filed"])["val"]
    return ytd["val"] + pann_v - pytd_v

def build_fundamentals(edgar):
    F = {}
    for t, cf in edgar.items():
        eq = _facts(cf, "StockholdersEquity") or _facts(
            cf, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
        F[t] = {"eq": eq,
                "liab": _facts(cf, "Liabilities"),
                "lse": _facts(cf, "LiabilitiesAndStockholdersEquity"),
                "assets": _facts(cf, "Assets"),
                "ni": _facts(cf, "NetIncomeLoss")}
    return F

def factors_asof(F, t, asof):
    """(de, roe, roa) point-in-time; None where not computable."""
    f = F[t]
    eq, eq_end = latest_instant(f["eq"], asof)
    assets, a_end = latest_instant(f["assets"], asof)
    liab = None
    if eq is not None:
        liab = instant_at(f["liab"], asof, eq_end)
        if liab is None:
            lse = instant_at(f["lse"], asof, eq_end)
            if lse is not None:
                liab = lse - eq
    if liab is None:
        liab, _ = latest_instant(f["liab"], asof)
    ni = ttm_ni(f["ni"], asof)
    de = (liab / eq) if (liab is not None and eq is not None and eq > 0) else None
    roe = (ni / eq) if (ni is not None and eq is not None and eq > 0) else None
    roa = (ni / assets) if (ni is not None and assets is not None and assets > 0) else None
    return de, roe, roa

# ------------------------------------------------------------ straddle pricing
_SPLIT_CACHE = {}

def unadj_close(sym, d, adj_close):
    """Actual traded close = split-adjusted close x cumulative later-split factor.
    (yfinance/Yahoo closes are retroactively split-adjusted; options strikes are
    in actual dollars, so ATM selection needs the real spot.)"""
    if sym not in _SPLIT_CACHE:
        os.makedirs("data_cache/splits", exist_ok=True)
        p = f"data_cache/splits/{sym}.parquet"
        if os.path.exists(p):
            s = pd.read_parquet(p)["ratio"]
        else:
            import yfinance as yf
            s = yf.Ticker(sym).splits
            s.index = pd.to_datetime(s.index).tz_localize(None)
            s.name = "ratio"
            s.to_frame().to_parquet(p)
        _SPLIT_CACHE[sym] = s
    s = _SPLIT_CACHE[sym]
    later = s[s.index > d]
    return adj_close * float(later.prod()) if len(later) else adj_close

def opt_symbol(sym, e):
    """OPRA parent symbol at date e (META traded as FB until 2022-06-09)."""
    if sym == "META" and e < pd.Timestamp("2022-06-09"):
        return "FB"
    return sym

def price_straddle(sym, e, px):
    """Price one ATM straddle at rebalance date `e`; 5-trading-day path of real
    mids. Returns dict or None (skip)."""
    idx = px.index
    pos = idx.get_loc(e)
    if pos + 5 >= len(idx):
        return None
    exit_date = idx[pos + 5]
    spot = unadj_close(sym, e, float(px.loc[e, "close"]))
    contracts = max(1, round(10000 / (spot * 100)))
    osym = opt_symbol(sym, e)
    cS = dbo.select_16d_modeled(osym, e, spot, iv_estimate=0.35, dte_min=30,
                                dte_max=75, dte_target=50, target_delta=0.50,
                                kind="call")
    pS = dbo.select_16d_modeled(osym, e, spot, iv_estimate=0.35, dte_min=30,
                                dte_max=75, dte_target=50, target_delta=0.50,
                                kind="put")
    if cS is None or pS is None:
        print(f"    {sym} {e.date()}: no option selected, skip", flush=True)
        return None
    cp = dbo.get_symbol_daily(cS.raw_symbol, e, exit_date)
    pq = dbo.get_symbol_daily(pS.raw_symbol, e, exit_date)
    if cp.empty or pq.empty:
        print(f"    {sym} {e.date()}: empty path ({cS.raw_symbol}), skip", flush=True)
        return None
    cp = cp.set_index("date")["mid"]; pq = pq.set_index("date")["mid"]
    if e not in cp.index or e not in pq.index:
        print(f"    {sym} {e.date()}: no entry mid, skip", flush=True)
        return None
    lc, lp = float(cp.loc[e]), float(pq.loc[e])
    d0 = lc + lp
    if d0 <= 0:
        return None
    vals = []                                   # straddle value each day after entry
    for dt in idx[pos + 1: pos + 6]:
        if dt in cp.index: lc = float(cp.loc[dt])
        if dt in pq.index: lp = float(pq.loc[dt])
        vals.append(lc + lp)
    return dict(spot=spot, contracts=contracts, strike=float(cS.strike),
                dte=int(cS.dte), d0=d0, vals=vals, exit_date=exit_date)

def price_with_retry(sym, e, px):
    for attempt in range(20):
        try:
            return price_straddle(sym, e, px)
        except Exception as ex:
            if "insufficient" in str(ex).lower():
                print("BUDGET WAIT", flush=True); time.sleep(300)
            else:
                print(f"  {sym} {e.date()} error: {ex}", flush=True)
                return None
    return None

def make_trade(sym, e, st, side, factor):
    """side=+1 long straddle, -1 short. Returns trade dict."""
    mult = 100 * st["contracts"]
    d0, vals = st["d0"], st["vals"]
    xv = vals[-1]
    pnl = side * (xv - d0) * mult - 4 * st["contracts"] * 2.0
    mae = min(0.0, min(side * (v - d0) for v in vals) * mult)
    return dict(symbol=sym, signal_type=f"{factor}_{'long' if side>0 else 'short'}",
                entry_date=e, exit_date=st["exit_date"], strike=st["strike"],
                dte=st["dte"], entry_iv=float("nan"), entry_delta=float("nan"),
                entry_credit=-side * d0 * mult, pnl=pnl,
                pnl_pct_credit=pnl / (d0 * mult), mae=mae,
                days_held=int((st["exit_date"] - e).days), exit_reason="t_5d")

# ---------------------------------------------------------------------- main
def main():
    rank_only = "--rank-only" in sys.argv
    edgar = ensure_edgar()
    F = build_fundamentals(edgar)

    cal = get_prices("AAPL", "2017-01-01", "2026-06-30").index    # trading calendar
    months = pd.period_range("2021-01", "2026-05", freq="M")
    rebals = [cal[cal >= m.start_time][0] for m in months]

    px = {t: get_prices(t, "2017-01-01", "2026-06-30") for t in UNIVERSE}

    FACTORS = ["de", "roe", "roa"]
    picks = {}                                   # (rebal, factor) -> (longs, shorts)
    for e in rebals:
        asof = e - pd.Timedelta(days=1)          # knowable strictly before entry
        vals = {t: factors_asof(F, t, asof) for t in UNIVERSE}
        for i, fac in enumerate(FACTORS):
            ranked = sorted(((v[i], t) for t, v in vals.items() if v[i] is not None),
                            reverse=True)
            if len(ranked) < 8:
                picks[(e, fac)] = ([], [])
                continue
            picks[(e, fac)] = ([t for _, t in ranked[:4]], [t for _, t in ranked[-4:]])
        if rank_only:
            print(e.date(), {f: picks[(e, f)] for f in FACTORS}, flush=True)
    if rank_only:
        return

    trades = {f: [] for f in FACTORS}
    for e in rebals:
        needed = sorted({t for f in FACTORS for grp in picks[(e, f)] for t in grp})
        cache = {}
        for t in needed:                         # price ONCE, reuse across factors
            cache[t] = price_with_retry(t, e, px[t])
        n_ok = sum(v is not None for v in cache.values())
        for fac in FACTORS:
            longs, shorts = picks[(e, fac)]
            for t in longs:
                if cache.get(t): trades[fac].append(make_trade(t, e, cache[t], +1, fac))
            for t in shorts:
                if cache.get(t): trades[fac].append(make_trade(t, e, cache[t], -1, fac))
        print(f"{e.date()} priced {n_ok}/{len(needed)} "
              f"de L{picks[(e,'de')][0]} S{picks[(e,'de')][1]}", flush=True)

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for fac in FACTORS:
        tdf = pd.DataFrame(trades[fac])
        if tdf.empty:
            print(f"{fac}: no trades"); continue
        db.save_run(tdf, summarize(tdf), phase=f"factor_{fac}", universe=UNIVERSE,
                    start="2021-01-01", end="2026-05-31", created_at=created,
                    notes=f"Sinclair factor straddles {fac}: long hi-Q ATM straddle,"
                          " short lo-Q, 5td hold, dte 30-75 tgt 50, $2/contract")
        wk = tdf.groupby("entry_date")["pnl"].sum()
        long_pl = tdf[tdf.signal_type.str.endswith("long")]["pnl"]
        short_pl = tdf[tdf.signal_type.str.endswith("short")]["pnl"]
        sharpe = wk.mean() / wk.std() * np.sqrt(52) if wk.std() > 0 else float("nan")
        print(f"\n=== {fac.upper()} ===")
        print(f"n weeks {len(wk)}  avg weekly PL ${wk.mean():,.0f}  best ${wk.max():,.0f}"
              f"  worst ${wk.min():,.0f}  Sharpe {sharpe:.2f}  hit {100*(wk>0).mean():.0f}%")
        print(f"long side: n={len(long_pl)} tot ${long_pl.sum():,.0f} avg ${long_pl.mean():,.0f}")
        print(f"short side: n={len(short_pl)} tot ${short_pl.sum():,.0f} avg ${short_pl.mean():,.0f}")

if __name__ == "__main__":
    main()
