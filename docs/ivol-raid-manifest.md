# IVolatility month — raid manifest (prepared 2026-07-22)

Sequence: 7-day FREE trial first → reconciliation gate → pay one month →
execute in priority order → cancel. Nothing runs before its kill bar is
written here.

## Gate 0 — reconciliation (trial week, before paying)
Pull ~20 trades we already priced from OPRA raw; IVol EOD prices must
reproduce our P&L within ±10%. Fail → vendor rejected, manifest void.
Also verify: billing is month-to-month cancellable; bulk pace fits quotas.

## Study 1 — per-name IV history download (the crown jewel)
Daily ~45d ATM IV (+16Δ if available) for the 30-name universe, max depth,
plus ES/NQ. Enables studies 2-5 and the scanner's dials from day one.

## Study 2 — name-IV slope dial (TJ's hypothesis, parked since 2026-07-09)
Test name-IV 5d slope as 5th light on the name-gate population.
Kill bar: must improve clean-basis $/tr or tail vs the 4-light line.

## Study 3 — earnings iron condors (censused 2026-07-17)
Implied-move vs realized on the calm-half names only (JNJ..AAPL class).
Kill bar: >= $40/tr after 4-leg costs, worst month tolerable; else grave.
Pre-registered: marginal-to-breakeven.

## Study 4 — stock-straddle tenor sweep + bull-put-spread wing pricing
(a) stock straddle 30/45/60d tenors on the Sleeve-3 names.
(b) MU-class bull put spreads: wing cost vs naked on the name-gate
population; kill bar: per-BPR efficiency must beat naked by >=3x with
per-trade >= $50. Pre-registered: licensed only as capacity variant.

## Study 5 — pure VRP-gap indicator (TJ, 2026-07-22)
Entries: gap = chainIV - RV20 >= {5,10,15} pts, variants {alone, +trend,
+storm lights, +earnings filter}; structure fixed (16d put, 50%/21DTE,
dedupe). Benchmark: name-gate clean (+$108/tr, worst -$843).
KILL BAR (pre-set): >= +$60/tr AND worst <= -$1,500 AND materially
non-overlapping with existing lines. Pre-registered: gap-alone fails the
tail; gap+lights collapses into name-gate.

## Study 6 — VRP harvested per line (bookkeeping)
With real IV series: recompute chainIV-vs-realized-after for every
historical line incl. futures (is MES true VRP? measured, not assumed).
