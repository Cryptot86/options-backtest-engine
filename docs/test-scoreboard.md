# Test Scoreboard — living list of every pending/validated scenario

*Rule: update this file every time a study opens, closes, or changes status.
Kill bars are written BEFORE runs. Concentration check (top-5 share of total)
is mandatory before any verdict is read.*

*Last updated: 2026-07-23*

## ✅ Validated / settled
| item | verdict | receipts |
|---|---|---|
| Gate-0 IVol reconciliation | vendor PASSES (MSFT ~3% mark diff) | commit be78320 |
| Study 1 — per-name IV series | DONE: 35 names + SPY, 13yr, dual basis (spot adj + spot_unadj) | data_cache/iv_series/stocks |
| Forecast-vs-realized edge | implied over-forecasts 63% of days, median +2.16 pts; vol-pts edge biggest when CHEAP (never read as "sell cheap") | forecast_vs_realized.py |
| VIX 3-green gate at scale | re-moated: 5DL $9→$79/tr, DD −90%, rescues JPM-class by rule | commit 3036a21 (re-run pending, see below) |
| 21-DTE law | stands; measured insurance ~$55/tr (CL calls); hold-to-exp doubles tail | run_21dte_counterfactual.py |
| Sizing law | qty=clamp(floor(2%·eq/anchor),1,3); anchors=worst-loss-reference.json | PLAYBOOK size-steps |
| YM (E-mini Dow) | NOT tested by decision — redundant ES beta, thin options; trade via MES | TJ 2026-07-23 |
| Split-basis law | strikes/notional on spot_unadj ONLY; ivx price & stock close are ADJUSTED | commit (fix) 2026-07-23 |

## 🔄 In flight
| item | status |
|---|---|
| Study 7 — pre-earnings straddle (buy D-10, sell pre-announcement) | clean re-run running; kill bar ≥+$40/tr pooled; pre-reg: dies |
| Study 3a — implied vs realized move, calm half | same run; decides whether 3b (condor) may exist |
| 35-name gated backtest RE-RUN on fixed basis | queued next — absolute $ not quotable until done |

## ⏳ Pending — ordered queue
1. **35-name gated re-run** (restores quotable numbers)
2. **Study 5 — VRP-gap indicator** ("TJ's realized-vs-forecasted-IV gap scanner").
   Entries: vrp_pts ≥ {5,10,15}, variants {alone, +trend, +lights, +earnings-filter}.
   KILL BAR: ≥+$60/tr AND worst ≤−$1,500 AND materially non-overlapping with
   existing lines. Pre-reg: gap-alone fails tail; gap+lights collapses into gate.
   Dial already computed daily for all 35 (vrp_pts) + dashboard IV tab plots it.
3. **#3 Crisis-peak fade** — iv_rank≥0.90 then 3 down-days → defined-risk put
   spread. All dials on disk; runs off the same trade table as Study 5.
4. **Study 2 — slope as 5th light (increment)** — does slope5 ADDED to the
   4-light name-gate improve $/tr or tail? Nearly free (filter analysis).
5. **Study 6 — VRP harvested per line** (bookkeeping; is MES true VRP?)
6. **Study 3b — earnings condor** — CONDITIONAL on 3a premise surviving
7. **Study 4a/4b** — straddle tenor sweep; bull-put-spread wing pricing
   (kill: ≥3× per-BPR vs naked, ≥$50/tr)
8. **#1 Term-structure carry gate** — term_pts column ready
9. **#6 Skew dial** — BLOCKED on phase-2 endpoint (16Δ/surface IV)
10. **#2 COT hedgers' bid** — new free CFTC pipe; most orthogonal
11. **#4 NG winter vol / #5 weekend theta** — cheap, low priority

## Data / infra notes
- Option pulls disk-cached permanently (data_cache/ivol_cache) — everything
  pulled this billing month is ours after cancel.
- LIVE VRP-gap after subscription ends: TradingView Pine cannot fetch chain IV;
  the pine scanner takes manual chain-IV input (lastChainIV) and the dashboard
  serves the historical dial. A live auto-refreshing gap scanner needs an
  ongoing IV source — decide near month-end (keep cheap tier vs manual input).
