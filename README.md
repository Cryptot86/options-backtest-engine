# options-backtest-engine

Backtests premium-selling options methods **as designed** (mechanical entry,
mechanical exit, disciplined size) to decide **keep / cut / rework** for each —
and to test whether technical indicators beat a plain volatility-risk-premium
(VRP) baseline. Realized P&L to date measures execution, not edge; this measures
edge.

## Layers

- **Layer 1 — signals** (`src/otbt/signals/`): underlying prices (yfinance) →
  technical signal ledger (RSI divergence, BB 2SD, 100-EMA bounce, BB 20SMA,
  5-day-low) plus the H6 VRP baseline.
- **Layer 2 — pricing** (`src/otbt/pricing/`): BS/Black-76 math + real-IV option
  data from Databento (OPRA equities), cache-first so re-runs cost $0.
- **Layer 3 — reporting** (`src/otbt/reporting/`): per-hypothesis metrics
  (n, freq, win%, expectancy, MAE, worst loss, Δ-vs-baseline).

## Phases

- **Phase 0** — reconstruct P&L from underlying path + realized-vol proxy
  (`run_backtest.py`). No option data. Good for direction/ranking.
- **Phase 1** — real-IV dollars from Databento (`run_backtest_real.py`).

## Setup

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
echo "DATABENTO_API_KEY=db-..." > .env      # never committed
```

## Data notes

- OPRA equity-options history starts **2013-04**; backtest window is 2013→2025
  (includes 2020 and 2022 vol events). Futures (GLBX) go back to 2010.
- All Databento pulls are cached under `data_cache/` (git-ignored). Historical
  data is immutable, so the API is only hit on a cache miss.
