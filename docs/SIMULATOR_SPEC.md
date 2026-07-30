# Simulator Spec — portfolio equity-curve engine (for the Titan app)

*Source of truth for values: `docs/rulebook.json` `_meta.allocation` + `_meta.sizing_engine`.
Reference implementations: `run_full_book.py` (full book), `run_theta_cap_sim.py`
(theta cap). This spec describes the engine the app should implement to replay/
forward-test the book and show its equity curve under all governors.*

## 1. Purpose
Given a stream of dated candidate trades, replay them day-by-day through every
risk governor and produce the equity curve + summary stats (CAGR, maxDD, MAR,
trades taken, skips by reason). Same engine runs backtest (historical trades) and
live paper-forward (today's signals). The point is capital protection first —
MAR (CAGR/maxDD), not raw return, is the score.

## 2. Inputs — one row per candidate trade
| field | meaning |
|---|---|
| `d` | entry date (D+1 of the signal) |
| `x` | exit date (= d + days_held; sim computes if only DTE known) |
| `pnl1` | realized P&L for ONE contract (sim scales by sized contracts) |
| `tag` | line id: EQ, MES, MCL, MNG, MGC, STRAD, LCALL |
| `cluster` | EQIDX / ENERGY / METALS / LONGVOL / LONGCALL |
| `book` | `sell` (short premium) or `buy` (debit: straddle / long call) |
| `margin` | buying-power used per contract |
| `strike` | option strike (for credit/theta proxy; 0 for futures) |
| `name` | dedupe key (e.g. `EQ:CRWD`) |

Live app replaces `pnl1` (unknown until exit) with mark-to-market and fills
`strike`/credit/theta from the real chain.

## 3. The daily loop (order matters)
For each calendar day from START to END:
1. **Close** every open position with `x <= day`; add its P&L to equity.
2. **Accrue idle yield**: `equity += max(equity - deployed_margin, 0) * RF`
   where `RF = annual_rate/252` (SGOV/T-bill ~4.5%; sim used 2% rate-honest).
3. **Measure** current cluster tails, used BPR (sell/buy), open names, and
   current aggregate daily theta (sum of open SELL positions' theta).
4. For each candidate entering today, run the GATE STACK (§4) in order; if it
   passes, size it (§5), open it, and update the running tallies; else increment
   the matching skip counter (`capacity`, `dedupe`, `theta`, `band`).
5. Record `equity` into the curve.
At the end, close any still-open positions. Stats: CAGR = (final/EQ0)^(1/yrs)-1;
maxDD = max peak-to-trough on the daily curve; MAR = CAGR/maxDD.

## 4. Gate stack — a candidate must pass ALL, in this order
1. **Entry gate (crash protection).** Stocks require VIX 3-green
   (rank≥50 + IV>realized + 5d-slope≤0); futures index/energy/metals are
   validated ungated. See `docs/GATES_EXPLAINED.md`. A trade whose signal wasn't
   gate-clean at signal close never enters. (In backtest the trade list is
   already gate-filtered; the live app applies the gate here.)
2. **Dedupe** (equity puts only): skip if the name is inside its **21-day loss
   cooldown** (LOSS_COOLDOWN_RULE); skip if `name` already open (**1 per name**);
   skip if **3 equity entries** already opened today (raised 2->3, 2026-07-30). `skip_reason='dedupe'`.
3. **Deployment band**: sell book used + new margin ≤ `sell_band * equity`
   (25% calm baseline; band mostly non-binding once caps+dedupe exist); buy book
   ≤ 15%. `skip_reason='band'`.
4. **Cluster tail caps**: sum(open worst-case in cluster) + new worst-case ≤
   cap·equity — EQIDX 7% · ENERGY 5% · METALS 5% · TOTAL 12%. `skip_reason='capacity'`.
   *(No theta gate here.)* Theta is a byproduct of position count × size, both
   already capped by sizing + cluster caps + dedupe. It is NOT a governor — see
   the monitoring invariant in §8.1.

## 5. Sizing (per line)
`contracts = clamp(floor(0.02 * equity / stress_anchor), 1, abs_ceil)`
then cluster room may reduce it: `contracts = min(contracts,
floor(room/stress_anchor))`; can return 0 → skip `capacity`. Anchors/ceils live
in `rulebook.json _meta.sizing_engine.stress_anchors`. `risk_pct=0.02` (do not
raise — MAR peaks ~3% then falls). Never size off broker BPR.

## 6. Theta proxy (until live chain theta is available)
Our trade store has no entry credit/theta, so the sim estimates it (generous /
upper-bound, so the cap is never understated):
- equity 16Δ put: `credit ≈ 0.02 * strike * 100` ; `theta = credit / DTE`, DTE=40
- futures micro : fixed credit/contract {MES 150, MCL 100, MNG 80, MGC 120} ;
  `theta = credit / DTE`
- long options (STRAD/LCALL): PAY theta → **not counted** toward collection.
**Live app: replace with the real per-position theta from the chain at fill.**
The 3% cap should then be checked against true aggregate theta each day.

## 7. Validated result (2015-2026, $50K start, full book) + theta-cap frontier
| theta cap | final | CAGR | maxDD | MAR | Θ-skips |
|---|---|---|---|---|---|
| none | $99,924 | 6.2% | 3.0% | 2.04 | 0 |
| 0.10% | $99,924 | 6.2% | 3.0% | 2.04 | 1 |
| 0.05% | $98,791 | 6.1% | 3.1% | 1.99 | 66 |
| **0.03%** | $95,494 | 5.8% | 3.1% | **1.85** | 180 |
| 0.02% | $93,487 | 5.6% | 3.2% | 1.76 | 346 |
| 0.01% | $86,800 | 4.9% | 3.4% | 1.43 | 686 |

KEY FINDING (2026-07-30): the book naturally runs at ≤0.06% daily theta. A cap
below that (0.03%, 0.02%, 0.01%) costs return AND does NOT reduce maxDD (it rises
slightly) — because theta is income, not risk; the drawdown source (adverse price
moves) is already governed by worst-loss sizing + cluster tail caps. So a theta
cap only pays as a BACKSTOP set ABOVE the operating range (~0.10-0.15% = free).
Break-even depends on the theta proxy (§6) — re-verify with live chain theta.
Deployment frontier: 25% BPR is optimal (same return as 55% BPR, ~half the DD).

## 8. Outputs the app should surface
`final_equity, cagr, maxDD, MAR, trades_taken, skips{capacity,dedupe,band},
max_theta_pct, equity_curve[]`. Show MAR and maxDD as the headline (not win%).
"Idle is normal" — empty energy/metals budgets are expected, not under-deployment.

### 8.1 Monitoring invariant — theta (ALARM ONLY, not a governor)
Aggregate daily theta of the SHORT book must stay ≤ **0.10% of net-liq**. This is
NOT a trade-blocking rule — it is a health check. By design theta cannot reach
this level: it is a byproduct of position count × size, both already bounded by
2% sizing + cluster caps (7/5/5, 12% total) + dedupe. The book's historical max
is 0.06%. Therefore:
- Do **not** skip trades on theta.
- Compute `daily_theta_pct = sum(open short theta) / net_liq` each day.
- If it EVER exceeds 0.10% → **raise an alarm / log** ("theta invariant breached —
  a sizing or cluster cap has failed; investigate"), do not silently continue.
It should never fire. Its firing means an upstream cap broke — that is the signal.
Tested: as a hard skip a theta cap below the operating range costs return with no
drawdown benefit (0.03% → MAR 2.04→1.85, maxDD unchanged); above it (≥0.10%) it
never binds. So the only correct form is alarm-only. (§7)
