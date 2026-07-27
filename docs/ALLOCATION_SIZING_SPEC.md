# Allocation & Sizing — implementation spec for Titan Trading app

*Handoff 2026-07-27. Source of truth for numbers: `docs/rulebook.json`
(`_meta.allocation` + `_meta.sizing_engine`) and `docs/worst-loss-reference.json`.
This doc is the human-readable algorithm; the app reads the JSON for values so
they never drift. All backtest-validated (13yr, OOS-split).*

## What this module does
Given (account equity, current VIX, open positions, an incoming signal), decide
**how many contracts** to trade — or **0 (skip)** with a reason. The app is a
DISCIPLINE LAYER: it makes the right size effortless and over-sizing impossible.

---

## The pipeline (evaluate in order; any step can return 0 → skip)

### STEP 0 — Regime → budgets (recompute daily from VIX)
```
sell_budget_pct = 0.25 if VIX < 25        # calm  (confirmed best)
                  0.50 if 25 <= VIX < 35   # gate sweet spot
                  0.60 if VIX >= 35        # never 100%
buy_budget_pct  = 0.15                      # flat, separate bucket
sell_budget_$   = sell_budget_pct * equity  # max MARGIN for the short-premium book
buy_budget_$    = buy_budget_pct  * equity  # for straddles + long calls
```
Two separate buckets: SELLING (short puts/calls) and BUYING (long vol/calls).
The ENERGY sleeve is NOT in the sell bucket — see Step 4.

### STEP 1 — Dedupe (hard rule, learned OOS)
- Same underlying + same day: multiple triggers (bb_2sd AND five_day_low) = **ONE** position. Never stack.
- Max **2 new equity entries per day**.
- One open position per line per market at a time.
→ fail = skip, `skip_reason='dedupe'`.

### STEP 2 — Per-line sizing (risk-based, scales with equity)
```
n = floor(risk_pct * equity / anchor)      # risk_pct = 0.02 (DO NOT raise)
n = clamp(n, 1, cap)
```
`anchor` and `cap` per line (from rulebook.json `lines[].sizing` and
`_meta.sizing_engine`):

| line | anchor $ | cap | cluster |
|---|---|---|---|
| stock put (5DL / bb_2sd) | 4520 | 1 | EQUITY_INDEX |
| ES / MES put | 1569 | 2 | EQUITY_INDEX |
| NQ / MNQ put | 2253 | 3 | EQUITY_INDEX |
| GC / MGC put | 823 | 2 | METALS |
| CL / MCL call | 290 (stress) | 10 (abs_ceil) | ENERGY |
| NG / MNG call | 200 (stress)* | 8 (abs_ceil) | ENERGY |
| straddle (Sleeve 3) | 6522 | 1 | LONG_VOL |

*NG stress-anchor is inflated ~4× over its $45 historical worst for the weather
tail — the one judgment number; revisit after a live winter. For energy the
`cap` is an absolute ceiling (prudence), not a risk cap.

### STEP 3 — Cluster tail check (concentration)
Positions in the SAME cluster share ONE tail budget (they lose together).
```
cluster_worst_open = sum(pos.contracts * pos.anchor for pos in open if pos.cluster == line.cluster)
room = cluster_cap_pct * equity - cluster_worst_open
n = min(n, floor(room / anchor))
if n < 1: SKIP (skip_reason='capacity')
```
Cluster caps (`worst-loss-reference.json _CLUSTERS` + `_meta.sizing_engine`):
- **EQUITY_INDEX** (stocks + ES + NQ; corr 0.93): shared budget. NOTE: the
  DEDUPE rule (Step 1) is the primary equity cluster fix — a hard equity cap
  REDUCED MAR in testing. Keep dedupe; apply a soft 5-7% cluster ceiling only
  as a backstop.
- **ENERGY** (CL + NG; corr 0.11): **separate 5% budget**, independent of the
  VIX sell bucket (it's diversifying, not competing). Confirmed: adding energy
  improved book MAR 0.49→0.56 with maxDD UNCHANGED.
- **METALS** (GC), **LONG_VOL** (straddle): independent.

### STEP 4 — Which budget does it draw from?
- SELL lines (stock/ES/NQ/GC puts) → must fit `sell_budget_$` (VIX-banded). If the
  new position's margin would exceed remaining sell budget → SKIP `capacity`.
- ENERGY calls (CL/NG) → draw from the **separate 5% energy tail cap** (Step 3),
  NOT the VIX sell budget. They only touch raw buying-power (tiny, ~$1-2K).
- BUY lines (straddle, long call) → must fit `buy_budget_$` (15%).

### STEP 5 — Emit
Return `contracts = n` (>=1) OR `0` with one of: `dedupe | capacity | habitat |
gate | manual`. Log every skip — a skipped valid signal is a *good* event
(~20% skip rate is the implicit correlation filter working, not a bug).

---

## Sizing worked example ($50K, calm VIX)
| line | formula | contracts |
|---|---|---|
| stock put | floor(1000/4520)→0→clamp 1 | **1** |
| MES put | floor(1000/1569)→0→clamp 1 | **1** |
| MCL call | floor(1000/290)=3, cap 10 | **3** |
| MNG call | floor(1000/200)=5, cap 8 | **5** |
| sell budget | 25% × 50k | **$12,500 margin ceiling** |
| energy tail budget | 5% × 50k | **$2,500** (MCL+MNG worst ≈ $1,870, fits) |

## Do-NOT list (guardrails, non-negotiable)
- Do NOT raise `risk_pct` above 2% (MAR peaks ~3% then falls; uncapped optimum was a leverage mirage).
- Do NOT size off broker BPR/margin — always the worst-loss/stress anchor (margin understates the tail).
- Do NOT raise VIX bands to force fills — capacity-skip is the discipline.
- Do NOT stack same-name same-day. Do NOT add a correlated position that breaches its cluster tail budget.
- Energy caps (CL 10 / NG 8) are absolute — they do NOT scale with wealth (some tails don't care how rich you are).

## Data the app must persist (already in Titan Ops data model)
- per trade: line, cluster, contracts, anchor, worst_case = contracts×anchor, budget_drawn (sell|buy|energy), skip_reason
- daily snapshot: equity, VIX, sell_budget_used/cap, buy_budget_used/cap, energy_tail_used/cap
- These power the equity curve, MAR, and the capacity/discipline reports.
