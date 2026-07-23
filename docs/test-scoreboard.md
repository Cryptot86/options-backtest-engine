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

## 🔄 In flight (chained overnight 2026-07-23→24; each starts when the prior ends)
| # | job | what it answers | log to check | ETA |
|---|---|---|---|---|
| 1 | 35-name gated RE-RUN (fixed split basis) | restores the quotable gate numbers ($9→$79/tr claim re-verified); recovers the bug's silent skips (e.g. GOOGL 5DL 86→111 trades) | `reports/gated_rerun_fixed.log` | ~4-5 h |
| 2 | Study 5 — VRP-gap indicator (TJ's ask) | is forecasted-vs-realized IV gap a tradeable entry? per-stock $ tables, kill bar ≥+$60/tr & worst ≥−$1,500 & non-overlapping | `reports/vrp_gap.log` | +~5.5 h |

**Self-serve status check:** `tail -20 reports/gated_rerun_fixed.log` and
`tail -40 reports/vrp_gap.log` — each prints per-cell lines while running and a
final verdict block when done. Ask Claude "show me the scoreboard" any time —
this file IS the memory.

## ⚰️ Closed 2026-07-23 (clean basis)
| item | verdict |
|---|---|
| **Study 7 — pre-earnings straddle** | **BURIED (2nd time), as pre-registered.** Clean run, 1,005 events, 98% coverage: +$26.6/tr pooled — below the +$40 bar. Win 39.5%, median −$52 (theta), tail real but thin (top-5 = 46%, ex-top5 +$14/tr). The ramp exists; after costs it doesn't pay enough. |
| **Study 3a — condor premise** | **SURVIVES.** 507 calm-half events: implied move 4.95% vs realized 2.52% — fear overpriced ~2× on 78% of events. Study 3b (4-leg condor) is UNLOCKED and justified. |

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
6. **Study 3b — earnings condor** — UNLOCKED (3a premise survived 2026-07-23)
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
