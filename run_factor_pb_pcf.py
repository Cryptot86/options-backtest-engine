"""Sinclair factor-sorted straddles (SEC EDGAR point-in-time fundamentals).

1. P/B  : LONG ATM straddles on HIGH price/book quartile, SHORT on LOW P/B quartile.
2. P/CF : LONG on LOW price/cashflow quartile, SHORT on HIGH P/CF quartile.

Rebalance first trading day of month 2021-01..2026-05, rank 15-name universe,
4 names per quartile leg, ATM straddles both legs, dte 30-75 target 50,
hold 5 trading days, exit at real mids, $2/contract costs.
Each (name, date) straddle priced ONCE and reused across both factor rankings.

Usage: python run_factor_pb_pcf.py [fund]   ("fund" = fundamentals check only)
"""
from dotenv import load_dotenv; load_dotenv()
import json
import os
import sys
import time as _t
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
            "NFLX", "AVGO", "JPM", "COST", "LLY", "UNH", "HD"]
EDGAR_DIR = os.path.join("data_cache", "edgar")
UA = {"User-Agent": "TJ Research vjm_tamil@yahoo.com"}
START, END = "2021-01-01", "2026-05-31"


# ---------------------------------------------------------------- EDGAR fetch
def _get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def _atomic_write(path, data):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _cached_json(path, fetch_fn):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    data = fetch_fn()
    _t.sleep(0.15)
    _atomic_write(path, data)
    return data


def load_facts():
    os.makedirs(EDGAR_DIR, exist_ok=True)
    tick = _cached_json(os.path.join(EDGAR_DIR, "company_tickers.json"),
                        lambda: _get_json("https://www.sec.gov/files/company_tickers.json"))
    cik = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}
    out = {}
    for s in UNIVERSE:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[s]:010d}.json"
        out[s] = _cached_json(os.path.join(EDGAR_DIR, f"{s}.json"),
                              lambda u=url: _get_json(u))
        print(f"EDGAR facts ready: {s}", flush=True)
    return out


def load_splits(sym):
    """Full split history (date -> ratio) via yfinance, cached next to EDGAR."""
    path = os.path.join(EDGAR_DIR, f"{sym}_splits.json")

    def _fetch():
        import yfinance as yf
        s = yf.Ticker(sym).splits
        return {str(pd.Timestamp(d).date()): float(v) for d, v in s.items()}

    return _cached_json(path, _fetch)


def load_noadj_close(sym):
    """Dividend-UNadjusted daily closes (Yahoo Close w/ auto_adjust=False:
    split-adjusted, dividend-unadjusted), cached. {date_str: close}."""
    path = os.path.join(EDGAR_DIR, f"{sym}_close_noadj.json")

    def _fetch():
        import yfinance as yf
        df = yf.download(sym, start="2020-12-01", end="2026-06-30",
                         auto_adjust=False, progress=False, actions=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return {str(pd.Timestamp(d).date()): float(v)
                for d, v in df["Close"].items() if pd.notna(v)}

    return _cached_json(path, _fetch)


def split_factor_after(splits, cover_date):
    """Product of split ratios strictly after `cover_date` (YYYY-MM-DD).
    Converts filing-date share counts to today's (adjusted-price) share basis."""
    f = 1.0
    for d, r in splits.items():
        if d > cover_date and r > 0:
            f *= r
    return f


# ------------------------------------------------------ point-in-time facts
def _units(facts, taxo, tag, unit):
    try:
        return facts["facts"][taxo][tag]["units"][unit]
    except KeyError:
        return []


def equity_asof(facts, D):
    """Latest known StockholdersEquity, using filed dates (point-in-time)."""
    for tag in ("StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"):
        es = [e for e in _units(facts, "us-gaap", tag, "USD")
              if e.get("filed", "9999") <= D and e.get("end")]
        if es:
            e = max(es, key=lambda e: (e["end"], e["filed"]))
            return float(e["val"])
    return None


def _yf_shares(sym):
    """Cached yfinance get_shares_full series (point-in-time actual counts)."""
    path = os.path.join(EDGAR_DIR, f"{sym}_yfshares.json")

    def _fetch():
        import yfinance as yf
        s = yf.Ticker(sym).get_shares_full(start="2019-01-01")
        s = s[~s.index.duplicated(keep="last")]
        return {str(pd.Timestamp(d).date()): float(v) for d, v in s.items()}

    return _cached_json(path, _fetch)


def shares_asof(facts, D, sym=None):
    """Point-in-time shares outstanding -> (shares, cover_date) or (None, None).
    1) dei:EntityCommonStockSharesOutstanding (sums share classes in the latest
       accession);  2) undimensioned us-gaap weighted-average basic shares
    (multi-class filers like META drop dimensioned dei facts from companyfacts);
    3) yfinance get_shares_full (GOOGL: no undimensioned share facts at all)."""
    es = [e for e in _units(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
          if e.get("filed", "9999") <= D and e.get("end")]
    if es:
        latest = max(e["filed"] for e in es)
        grp = [e for e in es if e["filed"] == latest]
        accn = max(grp, key=lambda e: e["end"])["accn"]
        rows = {(e["end"], float(e["val"])) for e in grp if e["accn"] == accn}
        return sum(v for _, v in rows), max(end for end, _ in rows)
    for tag in ("WeightedAverageNumberOfSharesOutstandingBasic",
                "WeightedAverageNumberOfDilutedSharesOutstanding"):
        es = [e for e in _units(facts, "us-gaap", tag, "shares")
              if e.get("filed", "9999") <= D and e.get("end")]
        if es:
            e = max(es, key=lambda e: (e["end"], e["filed"]))
            return float(e["val"]), e["end"]
    if sym is not None:
        sh = _yf_shares(sym)
        obs = [d for d in sh if d <= D]
        if obs:
            c = max(obs)
            return sh[c], c
    return None, None


def ocf_ttm_asof(facts, D):
    """Trailing-4Q operating cash flow known as of D:
    latest annual + latest post-FY YTD - prior-year comparable YTD."""
    for tag in ("NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"):
        es = [e for e in _units(facts, "us-gaap", tag, "USD")
              if e.get("filed", "9999") <= D and e.get("start") and e.get("end")]
        if not es:
            continue
        per = {}
        for e in es:                                   # dedupe periods, keep latest filed
            k = (e["start"], e["end"])
            if k not in per or e["filed"] > per[k]["filed"]:
                per[k] = e
        rows = list(per.values())
        for r in rows:
            r["dur"] = (pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).days
        ann = [r for r in rows if 330 <= r["dur"] <= 400]
        if not ann:
            continue
        a = max(ann, key=lambda r: r["end"])
        a_end = pd.Timestamp(a["end"])
        ytds = [r for r in rows if r["dur"] < 330
                and pd.Timestamp(r["start"]) > a_end
                and (pd.Timestamp(r["start"]) - a_end).days <= 10]
        if not ytds:
            return float(a["val"])                     # only the annual is known
        y = max(ytds, key=lambda r: r["end"])
        tgt = pd.Timestamp(y["end"]) - pd.Timedelta(days=365)
        prev = [r for r in rows
                if abs(r["dur"] - y["dur"]) <= 20
                and abs((pd.Timestamp(r["end"]) - tgt).days) <= 20]
        if not prev:
            return float(a["val"])
        p = min(prev, key=lambda r: abs((pd.Timestamp(r["end"]) - tgt).days))
        return float(a["val"]) + float(y["val"]) - float(p["val"])
    return None


# ------------------------------------------------------------- factor tables
def build_factors(facts_all, splits_all, noadj_all, rebs):
    """{reb_date: DataFrame(symbol, spot, pb, pcf)} — NaN where excluded.
    `spot` = as-traded price that day (what the option strikes are quoted in).
    mcap uses dividend-unadjusted close x point-in-time filed shares."""
    out = {}
    for d in rebs:
        D = d.strftime("%Y-%m-%d")
        rows = []
        for s in UNIVERSE:
            c = noadj_all[s].get(D)
            if c is None:
                continue
            spot = c * split_factor_after(splits_all[s], D)   # as-traded $
            sh, cover = shares_asof(facts_all[s], D, sym=s)
            if sh is None:
                continue
            mcap = c * sh * split_factor_after(splits_all[s], cover)
            eq = equity_asof(facts_all[s], D)
            cf = ocf_ttm_asof(facts_all[s], D)
            pb = mcap / eq if eq is not None and eq > 0 else np.nan
            pcf = mcap / cf if cf is not None and cf > 0 else np.nan
            rows.append(dict(symbol=s, spot=spot, mcap=mcap, pb=pb, pcf=pcf))
        out[d] = pd.DataFrame(rows)
    return out


def quartiles(tbl, col, n=4):
    """(top_n_high, bottom_n_low) symbol lists by `col`, valid names only."""
    v = tbl.dropna(subset=[col]).sort_values(col, ascending=False)
    if len(v) < 2 * n:
        return [], []
    return list(v["symbol"].head(n)), list(v["symbol"].tail(n))


# ---------------------------------------------------------- straddle pricing
def price_straddle(sym, e, spot, pxidx):
    """Price one ATM straddle held 5 trading days. Returns dict or None."""
    pos = pxidx.searchsorted(e)
    if pos + 5 >= len(pxidx):
        return None
    if sym == "META" and e < pd.Timestamp("2022-06-09"):
        sym = "FB"                      # Meta's OPRA root before the rename
    cS = dbo.select_16d_modeled(sym, e, spot, iv_estimate=0.35, dte_min=30,
                                dte_max=75, dte_target=50, target_delta=0.50,
                                kind="call")
    pS = dbo.select_16d_modeled(sym, e, spot, iv_estimate=0.35, dte_min=30,
                                dte_max=75, dte_target=50, target_delta=0.50,
                                kind="put")
    if cS is None or pS is None:
        return None
    cp = dbo.get_symbol_daily(cS.raw_symbol, e, cS.expiration)
    pq = dbo.get_symbol_daily(pS.raw_symbol, e, pS.expiration)
    if cp.empty or pq.empty:
        return None
    cp = cp.set_index("date")["mid"]
    pq = pq.set_index("date")["mid"]
    if e not in cp.index or e not in pq.index:       # entry mid must exist
        return None
    lc, lp = float(cp.loc[e]), float(pq.loc[e])
    d0 = lc + lp
    if d0 <= 0:
        return None
    vals = []
    for dt in pxidx[pos + 1:pos + 6]:                # 5 trading days, ffill mids
        if dt in cp.index:
            lc = float(cp.loc[dt])
        if dt in pq.index:
            lp = float(pq.loc[dt])
        vals.append(lc + lp)
    return dict(strike=float(cS.strike), dte=int(cS.dte), d0=d0, xv=vals[-1],
                path=vals, exit_date=pxidx[pos + 5])


def price_with_retry(sym, e, spot, pxidx):
    for _ in range(20):
        try:
            return price_straddle(sym, e, spot, pxidx)
        except Exception as ex:
            if "insufficient" in str(ex).lower():
                print("BUDGET WAIT", flush=True)
                _t.sleep(300)
            else:
                print(f"  skip {sym} {e.date()}: {ex}", flush=True)
                return None
    print(f"  skip {sym} {e.date()}: budget retries exhausted", flush=True)
    return None


def make_trade(sym, e, spot, st, side, tag):
    sign = 1 if side == "long" else -1
    contracts = max(1, round(10000 / (spot * 100)))
    mult = 100 * contracts
    pnl = sign * (st["xv"] - st["d0"]) * mult - 2.0 * 4 * contracts  # 4 fills RT
    mae = min(0.0, min(sign * (v - st["d0"]) for v in st["path"])) * mult
    return dict(symbol=sym, signal_type=f"{tag}_{side}",
                entry_date=e, exit_date=st["exit_date"], strike=st["strike"],
                dte=st["dte"], entry_iv=float("nan"), entry_delta=float("nan"),
                entry_credit=-sign * st["d0"] * mult, pnl=pnl,
                pnl_pct_credit=pnl / (st["d0"] * mult), mae=mae,
                days_held=int((st["exit_date"] - e).days), exit_reason="time_5d")


# --------------------------------------------------------------------- main
def weekly_report(name, trades):
    wk = trades.groupby("entry_date")["pnl"].sum().sort_index()
    sharpe = wk.mean() / wk.std() * np.sqrt(52) if wk.std() > 0 else float("nan")
    lg = trades[trades["signal_type"].str.endswith("_long")]["pnl"].sum()
    sh = trades[trades["signal_type"].str.endswith("_short")]["pnl"].sum()
    print(f"\n{name}", flush=True)
    print(f"  Average weekly PL : ${wk.mean():,.0f}")
    print(f"  Best week         : ${wk.max():,.0f}")
    print(f"  Worst week        : ${wk.min():,.0f}")
    print(f"  Sharpe ratio      : {sharpe:.2f}")
    print(f"  n weeks           : {len(wk)}")
    print(f"  Hit rate          : {100 * (wk > 0).mean():.0f}%")
    print(f"  Long legs total   : ${lg:,.0f}   Short legs total: ${sh:,.0f}",
          flush=True)


def main():
    facts_all = load_facts()
    splits_all = {s: load_splits(s) for s in UNIVERSE}
    noadj_all = {s: load_noadj_close(s) for s in UNIVERSE}
    px_all = {s: get_prices(s, "2017-01-01", "2026-06-30") for s in UNIVERSE}
    cal = px_all["AAPL"].index

    rebs = []
    for m in pd.period_range("2021-01", "2026-05", freq="M"):
        days = cal[(cal >= m.start_time) & (cal <= m.end_time)]
        if len(days):
            rebs.append(days[0])

    factors = build_factors(facts_all, splits_all, noadj_all, rebs)

    if len(sys.argv) > 1 and sys.argv[1] == "fund":
        for d in (rebs[0], rebs[len(rebs) // 2], rebs[-1]):
            t = factors[d].copy()
            t["mcap_B"] = (t["mcap"] / 1e9).round(0)
            print(f"\n== {d.date()} ==", flush=True)
            print(t[["symbol", "spot", "mcap_B", "pb", "pcf"]]
                  .round(2).to_string(index=False))
            hi_pb, lo_pb = quartiles(t, "pb")
            lo_pcf_hi, lo_pcf_lo = quartiles(t, "pcf")
            print(f"PB  long(high)={hi_pb} short(low)={lo_pb}")
            print(f"PCF long(low)={lo_pcf_lo} short(high)={lo_pcf_hi}")
        return

    straddle_cache = {}                      # (sym, date) -> priced dict|None
    trades_pb, trades_pcf = [], []
    for d in rebs:
        tbl = factors[d]
        pb_long, pb_short = quartiles(tbl, "pb")
        pcf_hi, pcf_lo = quartiles(tbl, "pcf")
        pcf_long, pcf_short = pcf_lo, pcf_hi         # long LOW P/CF, short HIGH
        legs = [("pb", "long", pb_long), ("pb", "short", pb_short),
                ("pcf", "long", pcf_long), ("pcf", "short", pcf_short)]
        need = sorted({s for _, _, syms in legs for s in syms})
        spots = dict(zip(tbl["symbol"], tbl["spot"]))       # as-traded $
        for s in need:
            if (s, d) not in straddle_cache:
                straddle_cache[(s, d)] = price_with_retry(
                    s, d, spots[s], px_all[s].index)
        n_ok = sum(1 for s in need if straddle_cache[(s, d)] is not None)
        for tag, side, syms in legs:
            sink = trades_pb if tag == "pb" else trades_pcf
            for s in syms:
                st = straddle_cache[(s, d)]
                if st is not None:
                    sink.append(make_trade(s, d, spots[s], st, side, tag))
        print(f"{d.date()}  PB L{pb_long}/S{pb_short}  "
              f"PCF L{pcf_long}/S{pcf_short}  priced {n_ok}/{len(need)}",
              flush=True)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ["symbol", "signal_type", "entry_date", "exit_date", "strike", "dte",
            "entry_iv", "entry_delta", "entry_credit", "pnl", "pnl_pct_credit",
            "mae", "days_held", "exit_reason"]
    for tag, rows, name in (("factor_pb", trades_pb, "P/B Straddle Trading Results"),
                            ("factor_pcf", trades_pcf, "P/CF Straddle Trading Results")):
        t = pd.DataFrame(rows)[cols]
        db.save_run(t, summarize(t), phase=tag, universe=UNIVERSE,
                    start=START, end=END, created_at=now,
                    notes=f"Sinclair factor-sorted ATM straddles ({tag}), "
                          "monthly rebalance, quartile long/short, hold 5td, "
                          "dte 30-75 tgt 50, $2/contract")
        weekly_report(name, t)
    print("\nFACTOR PB/PCF DONE", flush=True)


if __name__ == "__main__":
    main()
