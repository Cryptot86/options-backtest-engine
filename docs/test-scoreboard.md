# Test Scoreboard — living list of every pending/validated scenario

*Rule: update this file every time a study opens, closes, or changes status.
Kill bars are written BEFORE runs. MANDATORY before any verdict is read:
(1) concentration check (top-5 share), (2) NORMALIZE TO RISK — equal max-loss
per trade (raw dollars lie when position risk varies across names/eras).*

*Last updated: 2026-07-24*

## ✅ Validated / settled
| item | verdict | receipts |
|---|---|---|
| Gate-0 IVol reconciliation | vendor PASSES (MSFT ~3% mark diff) | commit be78320 |
| Study 1 — per-name IV series | DONE: 35 names + SPY, 13yr, dual basis (spot adj + spot_unadj) | data_cache/iv_series/stocks |
| Forecast-vs-realized edge | implied over-forecasts 63% of days, median +2.16 pts; vol-pts edge biggest when CHEAP (never read as "sell cheap") | forecast_vs_realized.py |
| VIX 3-green gate at scale | **CLEAN-BASIS FINAL (2026-07-24): 5DL $24→$129/tr (5.3×), eqDD $84.8K→$4.8K (−94%), n=349 (~26/yr), win 90%**; bug had UNDERSTATED the system (recovered split-name trades were profitable: ungated total $38.5K→$124.2K). Name-gate $62/tr = second. bb_2sd either-gate $162/tr n=55 | reports/gated_rerun_fixed.log |
| 21-DTE law | stands; measured insurance ~$55/tr (CL calls); hold-to-exp doubles tail | run_21dte_counterfactual.py |
| Sizing law | qty=clamp(floor(2%·eq/anchor),1,3); anchors=worst-loss-reference.json | PLAYBOOK size-steps |
| YM (E-mini Dow) | NOT tested by decision — redundant ES beta, thin options; trade via MES | TJ 2026-07-23 |
| Split-basis law | strikes/notional on spot_unadj ONLY; ivx price & stock close are ADJUSTED | commit (fix) 2026-07-23 |

## 🔄 In flight
(nothing running)

## ⚰️ Closed 2026-07-23 (clean basis)
| item | verdict |
|---|---|
| **Study 7 — pre-earnings straddle** | **BURIED (2nd time), as pre-registered.** Clean run, 1,005 events, 98% coverage: +$26.6/tr pooled — below the +$40 bar. Win 39.5%, median −$52 (theta), tail real but thin (top-5 = 46%, ex-top5 +$14/tr). The ramp exists; after costs it doesn't pay enough. |
| **Study 5 — VRP-gap indicator (TJ's ask)** | **BURIED per kill bar (2026-07-24), as pre-registered — but positively, with a lesson.** 7,502 entries priced. Best spec (gap≥15 +trend): +$48.4/tr < $60 bar; every meaningful cell breaches the −$1,500 tail (gap-alone worst −$16,313; NFLX Jan-2022 −$14.6K single trade). Overlap only 28% (that prong passed). WHY it fails: a huge IV-RV gap can't tell OVERPRICED fear from INFORMED fear — sometimes the market smells the event (NFLX, COP-COVID) and the gap is fair price for a bomb. gap+lights is WORSE than the plain VIX gate ($-11 vs +$129/tr): conditioning on big-gap + high-rank selects pre-event days. THE DIAL SURVIVES as a confirm light (name-gate light-3 = vrp>0, already law); it dies as a standalone entry. Trades kept: reports/vrp_gap_trades.csv |
| **#3 Crisis-peak fade** | **BURIED (2026-07-24).** Raw k=2 "passed" (+$35.7/tr) — a SIZING ILLUSION: spread width scales with stock price, so pre-split mega-caps carried 10-20x risk and clustered in the winning crashes. At EQUAL risk ($2K/trade): k=2 −$2.5/tr, k=3 −$13/tr, 17/35 names negative. Echo waves confirmed (TSLA/AMD/AAPL bleed). GATE MAP NOW COMPLETE: mid-and-stabilizing (3-green) is the ONLY harvestable seller cell. NEW LAW: normalize to risk before reading any dollar verdict. |
| **Study 3a — condor premise** | **SURVIVES.** 507 calm-half events: implied move 4.95% vs realized 2.52% — fear overpriced ~2× on 78% of events. Study 3b (4-leg condor) is UNLOCKED and justified. |

## ⏳ Pending — ordered queue
1. **#3 Crisis-peak fade** — iv_rank≥0.90 then 3 down-days → defined-risk put
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
