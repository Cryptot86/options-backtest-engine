#!/usr/bin/env python
"""Gate-0 SMOKE TEST — "is the Lab plan what we need?"

For the 30-name universe, verify IVol can deliver the data our studies need:
  1. stock EOD OHLC pulls at all
  2. an option chain pulls for the same day
  3. the FIELDS we depend on are present, especially:
       - per-contract option OHLC (open/high/low) — the fear-envelope question
       - IV + greeks   (dials: VRP gap, IV rank, term structure, skew)
       - open interest (liquidity floor for the 9:30-open proxy)

Prints a per-symbol presence matrix + a single GO / NO-GO verdict. This is the
"does the plan fit before we let the month bill" check. Read-only, ~1 req/sec.

Usage:
  python gate0_smoke.py                 # probe all 30 on a recent trading day
  python gate0_smoke.py --date 2026-07-20 --symbols MSFT AAPL NVDA
  python gate0_smoke.py --dry-run       # show the plan without hitting the API
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from src.otbt.pricing import ivol_client as iv

# 30 single-name stocks we already track (data_cache) — ETFs/index excluded.
UNIVERSE_30 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "CRM", "COST", "LLY", "UNH", "JNJ", "PFE", "JPM", "BAC", "WFC", "GS",
    "XOM", "CVX", "COP", "CAT", "DE", "BA", "HD", "MCD", "NKE", "DIS",
]

OHLC_COLS  = ("open", "high", "low")
GREEK_COLS = ("delta", "gamma", "theta", "vega")
OI_COLS    = ("open interest", "open_interest", "oi", "openinterest")


def _has(df: pd.DataFrame, cands) -> bool:
    cols = {c.lower() for c in df.columns}
    return any(c in cols for c in cands)


def probe(symbol: str, day: str) -> iv.ProbeResult:
    """Real flow: stock EOD -> list contracts near-ATM ~40 DTE -> pull one
    contract's EOD record -> inspect which fields the plan actually returns."""
    # 1. stock OHLC (small window so a holiday still returns rows)
    try:
        s = iv.stock_ohlc(symbol, day, day)
        stock_ok = not s.empty and _has(s, ("close",))
        spot = float(s.iloc[0]["close"]) if stock_ok else None
    except Exception as e:
        return iv.ProbeResult(symbol, False, False, False, False, False, False, 0,
                              note=f"stock err: {e}")
    if not stock_ok:
        return iv.ProbeResult(symbol, False, False, False, False, False, False, 0,
                              note="no stock close (try another --date)")
    # 2. list contracts ~40 DTE, +/-8% around spot
    try:
        exp_lo = (pd.Timestamp(day) + pd.Timedelta(days=25)).strftime("%Y-%m-%d")
        exp_hi = (pd.Timestamp(day) + pd.Timedelta(days=55)).strftime("%Y-%m-%d")
        contracts = iv.list_contracts(symbol, day, exp_lo, exp_hi,
                                      round(spot * 0.92, 2), round(spot * 1.08, 2), "P")
    except Exception as e:
        return iv.ProbeResult(symbol, True, False, False, False, False, False, 0,
                              note=f"lookup err: {e}")
    if contracts.empty:
        return iv.ProbeResult(symbol, True, False, False, False, False, False, 0,
                              note="no contracts in window (try another --date)")
    # 3. pull ONE contract's EOD record to inspect fields
    try:
        contracts["strike"] = contracts["strike"].astype(float)
        atm = contracts.iloc[(contracts["strike"] - spot).abs().argmin()]
        rec = iv.option_eod(int(atm["optionid"]), day, day)
    except Exception as e:
        return iv.ProbeResult(symbol, True, True, False, False, False, False,
                              len(contracts), note=f"eod err: {e}")
    return iv.ProbeResult(
        symbol=symbol,
        stock_ok=True,
        chain_ok=True,
        per_contract_ohlc=(not rec.empty and _has(rec, OHLC_COLS)),
        has_iv=(not rec.empty and _has(rec, ("iv",))),
        has_greeks=(not rec.empty and all(_has(rec, (g,)) for g in GREEK_COLS)),
        has_oi=(not rec.empty and _has(rec, OI_COLS)),
        n_contracts=len(contracts),
        note="" if not rec.empty else "contract EOD empty",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-07-20", help="trading day to probe")
    ap.add_argument("--symbols", nargs="*", default=UNIVERSE_30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        print(f"DRY RUN — would probe {len(a.symbols)} symbols on {a.date} "
              f"at ~1 req/sec (~{len(a.symbols)*2}s):")
        print("  ", ", ".join(a.symbols))
        print(f"  base={iv.BASE}")
        print("  endpoints:", iv.EP_STOCK_EOD, "|", iv.EP_OPT_EOD)
        print("Set IVOL_API_KEY in .env, drop --dry-run, and re-run.")
        return 0

    rows = []
    for i, sym in enumerate(a.symbols, 1):
        r = probe(sym, a.date)
        rows.append(r)
        flag = "OK " if (r.stock_ok and r.chain_ok) else "!! "
        print(f"[{i:>2}/{len(a.symbols)}] {flag}{sym:<6} "
              f"stock={'Y' if r.stock_ok else 'N'} chain={'Y' if r.chain_ok else 'N'} "
              f"opt_OHLC={'Y' if r.per_contract_ohlc else 'N'} "
              f"IV={'Y' if r.has_iv else 'N'} greeks={'Y' if r.has_greeks else 'N'} "
              f"OI={'Y' if r.has_oi else 'N'} n={r.n_contracts}"
              + (f"  <{r.note}>" if r.note else ""), flush=True)

    df = pd.DataFrame([r.__dict__ for r in rows])
    n = len(df)
    print("\n================ GATE-0 SMOKE SUMMARY ================")
    print(f"symbols probed        : {n}")
    print(f"stock OHLC ok         : {df.stock_ok.sum()}/{n}")
    print(f"option chain ok       : {df.chain_ok.sum()}/{n}")
    print(f"per-contract OHLC     : {df.per_contract_ohlc.sum()}/{n}  "
          f"(the fear-envelope / 9:30-open question)")
    print(f"IV present            : {df.has_iv.sum()}/{n}")
    print(f"greeks present        : {df.has_greeks.sum()}/{n}")
    print(f"open interest present : {df.has_oi.sum()}/{n}")

    # Verdict: we REQUIRE stock+chain+IV+greeks on ~all names. OHLC is a bonus.
    core = df.stock_ok & df.chain_ok & df.has_iv & df.has_greeks
    ok = core.mean() >= 0.90
    print("\nVERDICT:", "GO — core data present, plan fits." if ok
          else "NO-GO — core data missing; do not let the month bill. See failures above.")
    if df.per_contract_ohlc.sum() == 0:
        print("NOTE: no per-contract OHLC found -> close-only path (fine per TJ); "
              "fear-envelope stays a nice-to-have, not available.")
    elif df.per_contract_ohlc.sum() >= 0.9 * n:
        print("BONUS: per-contract OHLC present -> fear-envelope (winners' intraday "
              "MAE) is available as a reference series.")
    df.to_csv("reports/gate0_smoke_result.csv", index=False)
    print("\nwrote reports/gate0_smoke_result.csv")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
