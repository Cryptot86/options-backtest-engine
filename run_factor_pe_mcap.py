"""Sinclair factor-sorted straddle test (book replication).

Strategy 1 "P/E Straddle Trading Results":
  LONG ATM straddles on the LOWEST-P/E quartile, SHORT on the HIGHEST-P/E quartile.
Strategy 2 "Market Capitalization Trading Results":
  LONG straddles on the HIGH-cap quartile, SHORT on the LOW-cap quartile.

Mechanics: rebalance first trading day of each month 2021-01..2026-05; ATM
straddle at the 2nd monthly expiry (dte 30-75, target 50); contracts =
max(1, round(10000/(spot*100))); hold 5 trading days, exit both legs at real
marks; $2/contract per fill (4 fills per straddle round trip).

Point-in-time factors (free yfinance; cached in the session scratchpad):
  P/E  = split-adjusted close / trailing-4-quarter Reported EPS (Yahoo's EPS
         history is split-adjusted, verified on AMZN 2021), using only quarters
         REPORTED before the rebalance date; negative trailing EPS -> excluded.
  MCap = ACTUAL price * ACTUAL shares. Yahoo prices are always split-adjusted,
         so actual price(t) = close(t) * prod(split ratios AFTER t); shares
         come from get_shares_full (actual counts at t, ffilled).
Option selection + sizing use the ACTUAL traded spot (strikes are listed in
actual terms, e.g. AMZN ~3200 in 2021, not the back-adjusted ~160).
"""
from dotenv import load_dotenv; load_dotenv()
import os
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from types import SimpleNamespace

from src.otbt.data import db
from src.otbt.reporting.metrics import summarize
from src.otbt.pricing import databento_options as dbo
from src.otbt.pricing.blackscholes import strike_for_delta

UNIV = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
        "NFLX", "AVGO", "JPM", "COST", "LLY", "UNH", "HD"]
CACHE = ("/private/tmp/claude-501/-Users-bhuvitamil-Documents-TJ-Options-Trading/"
         "fc440fb4-da78-4300-83f4-623695102aed/scratchpad/factor_cache")
CKPT = os.path.join(CACHE, "trades_checkpoint.parquet")
HOLD_DAYS = 5
COST_PER_FILL = 2.0          # $/contract per fill; straddle round trip = 4 fills
os.makedirs(CACHE, exist_ok=True)


# ------------------------------------------------------------------ prefetch
def _cached(name, fetch):
    p = os.path.join(CACHE, name + ".parquet")
    if os.path.exists(p):
        return pd.read_parquet(p)
    df = fetch()
    df.to_parquet(p)
    return df


def prefetch(sym):
    import yfinance as yf
    tk = yf.Ticker(sym)

    def _earn():
        ed = tk.get_earnings_dates(limit=60).reset_index()
        ed.columns = [str(c) for c in ed.columns]
        return ed

    def _shares():
        try:
            sh = tk.get_shares_full(start="2020-06-01")
        except Exception as e:
            print(f"{sym}: get_shares_full error: {e}", flush=True)
            sh = None
        if sh is not None and len(sh):
            out = sh.to_frame("shares").reset_index()
            out.columns = ["date", "shares"]
            out["source"] = "shares_full"
        else:
            const = float(tk.fast_info["shares"])
            out = pd.DataFrame({"date": [pd.Timestamp("2020-06-01")],
                                "shares": [const], "source": ["fast_info_const"]})
            print(f"{sym}: FALLBACK constant fast_info shares={const:,.0f}", flush=True)
        return out

    def _close():
        import yfinance as yf2
        raw = yf2.download(sym, start="2020-06-01", end="2026-06-30",
                           auto_adjust=False, progress=False, actions=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        out = raw[["Close"]].rename(columns={"Close": "close"})
        out.index = pd.to_datetime(out.index)
        out.index.name = "date"
        return out

    def _splits():
        sp = tk.splits
        if sp is None or not len(sp):
            return pd.DataFrame({"date": pd.to_datetime([]), "ratio": []})
        out = sp.to_frame("ratio").reset_index()
        out.columns = ["date", "ratio"]
        return out

    return (_cached(f"earnings_{sym}", _earn), _cached(f"shares_{sym}", _shares),
            _cached(f"rawclose_{sym}", _close), _cached(f"splits_{sym}", _splits))


# ---------------------------------------------------------------- factor data
close = {}     # split-adjusted (not div-adjusted) close, today's units
rvol = {}
eps_hist = {}  # [report_date, eps] (split-adjusted EPS)
shares = {}    # actual shares outstanding series
splits = {}    # split ratio series
for s in UNIV:
    e, sh, rc, sp = prefetch(s)

    close[s] = rc["close"]
    lr = np.log(close[s]).diff()
    rvol[s] = (lr.rolling(20).std() * np.sqrt(252)).dropna()

    dcol = e.columns[0]
    e[dcol] = pd.to_datetime(e[dcol]).dt.tz_localize(None).dt.normalize()
    e = e[e["Reported EPS"].notna()][[dcol, "Reported EPS"]]
    e = e.rename(columns={dcol: "report_date", "Reported EPS": "eps"})
    eps_hist[s] = e.drop_duplicates("report_date").sort_values("report_date")

    sh["date"] = pd.to_datetime(sh["date"]).dt.tz_localize(None).dt.normalize()
    shares[s] = sh.groupby("date")["shares"].last().sort_index()

    sp["date"] = pd.to_datetime(sp["date"]).dt.tz_localize(None).dt.normalize()
    splits[s] = sp.set_index("date")["ratio"].sort_index()

cal = close["AAPL"].index  # trading calendar


def ttm_eps(sym, d):
    e = eps_hist[sym]
    past = e[e["report_date"] < d]
    if len(past) < 4:
        return None
    return float(past["eps"].iloc[-4:].sum())


def shares_on(sym, d):
    ss = shares[sym]
    past = ss[ss.index <= d]
    return float(past.iloc[-1]) if len(past) else float(ss.iloc[0])  # bfill early


def cumfactor(sym, d):
    """Product of split ratios AFTER d: converts today's-unit price to actual."""
    sp = splits[sym]
    fut = sp[sp.index > d]
    return float(fut.prod()) if len(fut) else 1.0


def px(series, d):
    ss = series[series.index <= d]
    return float(ss.iloc[-1]) if len(ss) else None


def actual_spot(sym, d):
    return px(close[sym], d) * cumfactor(sym, d)


# --------------------------------------------------------------- rebalances
months = pd.period_range("2021-01", "2026-05", freq="M")
rebals = []
for m in months:
    days = cal[(cal >= m.start_time) & (cal <= m.end_time)]
    if len(days):
        rebals.append(days[0])


# ------------------------------------------------------------- straddle P&L
FB_CUTOVER = pd.Timestamp("2022-06-09")  # Facebook options rooted FB before this


def select_atm(osym, d, spot, iv, kind):
    """Model-placed ~50-delta strike at the 2nd-monthly expiry (dte 30-75,
    target 50), snapped to the listed ladder. Local copy of the library's
    select_16d_modeled WITHOUT its split-scale heuristic: we pass the ACTUAL
    raw-terms spot, and that heuristic misreads crash regimes (post-crash
    ladders have median ~2x spot, e.g. NFLX/META 2022) as split mismatches."""
    defs = dbo.get_definitions(osym, d)
    if defs.empty:
        return None
    cls = "P" if kind == "put" else "C"
    df = defs[defs["instrument_class"] == cls].copy()
    if df.empty:
        return None
    df["dte"] = (df["expiration"] - pd.Timestamp(d)).dt.days
    df = df[(df["dte"] >= 30) & (df["dte"] <= 75)]
    if df.empty:
        return None
    exp = df.iloc[(df["dte"] - 50).abs().argsort().iloc[0]]["dte"]
    df = df[df["dte"] == exp]
    T = int(exp) / 365.0
    iv_use = max(iv * 1.15, 0.06)
    K_star = strike_for_delta(spot, T, iv_use, 0.50, kind=kind)
    r = df.iloc[(df["strike_price"] - K_star).abs().argsort().iloc[0]]
    return SimpleNamespace(raw_symbol=str(r["raw_symbol"]),
                           strike=float(r["strike_price"]),
                           expiration=pd.Timestamp(r["expiration"]),
                           dte=int(r["dte"]))


def price_straddle(sym, d, exit_date):
    """One ATM straddle priced LONG (multiplier 1). Returns dict or None."""
    spot = actual_spot(sym, d)
    iv = float(rvol[sym].loc[:d].iloc[-1])
    # pre-2022-06 "META.OPT" resolves to Metamaterial Inc; Facebook was FB
    osym = "FB" if sym == "META" and d < FB_CUTOVER else sym
    cS = select_atm(osym, d, spot, iv, kind="call")
    pS = select_atm(osym, d, spot, iv, kind="put")
    if cS is None or pS is None:
        print(f"    {sym} {d.date()}: no option selected, skip", flush=True)
        return None
    if abs(cS.strike / spot - 1) > 0.25 or abs(pS.strike / spot - 1) > 0.25:
        print(f"    {sym} {d.date()}: strike {cS.strike}/{pS.strike} far from "
              f"spot {spot:.1f} (symbology collision?), skip", flush=True)
        return None
    cp = dbo.get_symbol_daily(cS.raw_symbol, d, exit_date)
    pq = dbo.get_symbol_daily(pS.raw_symbol, d, exit_date)
    if cp.empty or pq.empty:
        print(f"    {sym} {d.date()}: empty path, skip", flush=True)
        return None
    cp = cp.set_index("date")["mid"]
    pq = pq.set_index("date")["mid"]
    if d not in cp.index or d not in pq.index:
        print(f"    {sym} {d.date()}: no entry mid, skip", flush=True)
        return None
    days = cal[(cal >= d) & (cal <= exit_date)]
    lc, lp = float(cp.loc[d]), float(pq.loc[d])
    v0 = lc + lp
    if v0 <= 0:
        return None
    lo = hi = v0
    for dt in days[1:]:
        if dt in cp.index:
            lc = float(cp.loc[dt])
        if dt in pq.index:
            lp = float(pq.loc[dt])
        lo, hi = min(lo, lc + lp), max(hi, lc + lp)
    v1 = lc + lp  # last known marks at/before exit date (legs ffilled)
    contracts = max(1, round(10000.0 / (spot * 100.0)))
    return dict(spot=spot, iv=iv, strike_c=float(cS.strike),
                strike_p=float(pS.strike), dte=int(cS.dte), v0=v0, v1=v1,
                lo=lo, hi=hi, contracts=contracts)


def make_trade(sym, d, exit_date, sp, side, signal_type):
    c, v0, v1 = sp["contracts"], sp["v0"], sp["v1"]
    pnl = (v1 - v0) * 100.0 * c * side - COST_PER_FILL * 4 * c
    if side > 0:
        mae = (sp["lo"] - v0) * 100.0 * c
    else:
        mae = (v0 - sp["hi"]) * 100.0 * c
    mae = min(mae, 0.0)
    notional = v0 * 100.0 * c
    return dict(symbol=sym, signal_type=signal_type, entry_date=d,
                exit_date=exit_date, strike=sp["strike_c"], dte=sp["dte"],
                entry_iv=sp["iv"], entry_delta=float("nan"),
                entry_credit=notional * (1 if side < 0 else -1),
                pnl=pnl, pnl_pct_credit=pnl / notional, mae=mae,
                days_held=int((exit_date - d).days), exit_reason="time_5d",
                strike_put=sp["strike_p"], contracts=c, spot=sp["spot"],
                side="long" if side > 0 else "short")


# ------------------------------------------------------------------ main loop
done_dates = set()
all_rows = []
if os.path.exists(CKPT):
    prev = pd.read_parquet(CKPT)
    # scrub rebalances contaminated by the META/Metamaterial symbology collision
    # (2022-01..05 priced Facebook exposure off the wrong options root); they
    # get re-done below with the FB mapping. Idempotent: keyed on the bad row.
    ed = pd.to_datetime(prev["entry_date"])
    bad = ((prev["symbol"] == "META") & (prev["strike"] < prev["spot"] * 0.5)).any()
    if bad:
        drop = (ed >= "2022-01-01") & (ed <= "2022-05-31")
        print(f"scrubbing {int(drop.sum())} contaminated rows (2022-01..05)", flush=True)
        prev = prev[~drop]
        prev.to_parquet(CKPT)
    # one-shot: redo dates priced with the library's split-scale heuristic,
    # which skipped crash-regime names (NFLX/META 2022). Re-doing a date is
    # ~free (paths cached); marker prevents rescrub of legit partial dates.
    marker = os.path.join(CACHE, "scrub_incomplete.done")
    if not os.path.exists(marker):
        ed = pd.to_datetime(prev["entry_date"])
        counts = ed.value_counts()
        redo = set(counts[counts < 16].index)
        if redo:
            print(f"re-doing {len(redo)} incomplete rebalances: "
                  f"{sorted(str(x.date()) for x in redo)}", flush=True)
            prev = prev[~ed.isin(redo)]
            prev.to_parquet(CKPT)
        with open(marker, "w") as f:
            f.write("done")
    all_rows = prev.to_dict("records")
    done_dates = set(pd.to_datetime(prev["entry_date"]).unique())
    print(f"resuming: {len(done_dates)} rebalances already done", flush=True)

for d in rebals:
    if pd.Timestamp(d) in done_dates:
        continue
    pos = cal.get_loc(d)
    if pos + HOLD_DAYS >= len(cal):
        print(f"{d.date()}: not enough forward days, stop", flush=True)
        break
    exit_date = cal[pos + HOLD_DAYS]

    # --- factor ranks ---
    pe, mc = {}, {}
    for s in UNIV:
        t = ttm_eps(s, d)
        if t is not None and t > 0:
            pe[s] = px(close[s], d) / t
        mc[s] = actual_spot(s, d) * shares_on(s, d)
    pes = pd.Series(pe).sort_values()
    mcs = pd.Series(mc).sort_values()
    k = 4 if len(pes) >= 8 else len(pes) // 2
    pe_long, pe_short = list(pes.index[:k]), list(pes.index[-k:])
    mc_long, mc_short = list(mcs.index[-4:]), list(mcs.index[:4])
    print(f"\n{d.date()} -> exit {exit_date.date()} | "
          f"PE long={pe_long} short={pe_short} | "
          f"MCAP long={mc_long} short={mc_short}", flush=True)

    # --- price each unique straddle once, reuse across strategies ---
    need = sorted(set(pe_long + pe_short + mc_long + mc_short))
    priced = {}
    for s in need:
        for attempt in range(20):
            try:
                priced[s] = price_straddle(s, d, exit_date)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower():
                    print("BUDGET WAIT", flush=True)
                    time.sleep(300)
                else:
                    print(f"    {s} {d.date()}: ERROR {ex}", flush=True)
                    priced[s] = None
                    break
        else:
            priced[s] = None

    for names, side, sig in ((pe_long, +1, "pe_long"), (pe_short, -1, "pe_short"),
                             (mc_long, +1, "mcap_long"), (mc_short, -1, "mcap_short")):
        for s in names:
            if priced.get(s) is not None:
                all_rows.append(make_trade(s, d, exit_date, priced[s], side, sig))

    t = pd.DataFrame(all_rows)
    t.to_parquet(CKPT)
    cur = t[pd.to_datetime(t["entry_date"]) == d]
    for strat, sigs in (("PE", ("pe_long", "pe_short")),
                        ("MCAP", ("mcap_long", "mcap_short"))):
        g = cur[cur["signal_type"].isin(sigs)]
        print(f"  {strat}: n={len(g)} pnl=${g['pnl'].sum():,.0f}", flush=True)

# --------------------------------------------------------------- reporting
trades = pd.DataFrame(all_rows)
trades["entry_date"] = pd.to_datetime(trades["entry_date"])
trades["exit_date"] = pd.to_datetime(trades["exit_date"])
created = datetime.now(timezone.utc).isoformat(timespec="seconds")


def report(name, sigs, phase):
    t = trades[trades["signal_type"].isin(sigs)].copy()
    weekly = t.groupby("entry_date")["pnl"].sum()
    mu, sd = weekly.mean(), weekly.std()
    sharpe = mu / sd * np.sqrt(52) if sd > 0 else float("nan")
    long_pnl = t[t["side"] == "long"]["pnl"].sum()
    short_pnl = t[t["side"] == "short"]["pnl"].sum()
    print(f"\n=== {name} ===")
    print(f"Average weekly PL: ${mu:,.0f}")
    print(f"Best week: ${weekly.max():,.0f}")
    print(f"Worst week: ${weekly.min():,.0f}")
    print(f"Sharpe ratio: {sharpe:.2f}")
    print(f"n weeks: {len(weekly)} | hit rate: {100*(weekly>0).mean():.0f}% | "
          f"total: ${weekly.sum():,.0f}")
    print(f"long-side PL: ${long_pnl:,.0f} | short-side PL: ${short_pnl:,.0f}")
    print(f"trades: {len(t)} | per-trade hit: {100*(t['pnl']>0).mean():.0f}%")
    cols = ["symbol", "signal_type", "entry_date", "exit_date", "strike", "dte",
            "entry_iv", "entry_delta", "entry_credit", "pnl", "pnl_pct_credit",
            "mae", "days_held", "exit_reason", "strike_put", "contracts",
            "spot", "side"]
    run_id = db.save_run(t[cols], summarize(t), phase=phase, universe=UNIV,
                         start="2021-01-01", end="2026-05-31",
                         created_at=created,
                         notes=f"Sinclair factor straddles: {name}; ATM dte~50, "
                               f"hold 5td, $10K/name, $2/contract/fill")
    print(f"saved run_id={run_id} phase={phase}")


report("P/E Straddle Trading Results", ("pe_long", "pe_short"), "factor_pe")
report("Market Capitalization Trading Results",
       ("mcap_long", "mcap_short"), "factor_mcap")
print("\nFACTOR PE/MCAP DONE")
