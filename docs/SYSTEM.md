# THE SYSTEM — one page, every component

*The engine finds the dimes; discipline refuses the dollar.*

## The decision pipeline (every trade passes all five)
1. **HABITAT** — is this market licensed? (whitelist: ES/MES + NQ/MNQ + GC puts,
   NG/CL calls, stocks-as-class; blacklist: NG puts, NQ calls, HG, 6E, naked
   strangles, YM-by-decision)
2. **GATE** — is the vol-state paying? VIX 3-green: rank≥50% + VIX>realized +
   5d slope≤0. Stocks require it (alt: name-gate 4-light, candidate). ES/MES
   validated ungated. The ONLY harvestable seller cell (gate map complete).
3. **ENTRY** — price signal: 2-SD dip or 5-day low, in uptrend (10>100 EMA).
   Calls mirror: 2-SD rally in downtrend (NG/CL only).
4. **SIZE** — qty = clamp(floor(2% × equity / line worst-loss anchor), 1, 3).
   Anchors + cluster budgets: docs/worst-loss-reference.json. Correlated
   positions share ONE tail budget (ES~NQ 0.93). Never size on conviction.
5. **MANAGE** — 50% profit OR 21 DTE OR trend-invalidation. NO price stops
   (receipts: stops double losses). No rolling 5DL-class. One position per
   line per market.

## Sleeves
- **Sleeve 1-2**: short premium with-trend (the core; +$129/tr gated stocks,
  MES/GC/NQ puts, NG/CL calls)
- **Sleeve 3**: long vol when cheap (ATM straddle, rank≤30 & IV<RV;
  +50%/−40%/21DTE) — buyer's cell
- **Candidates in trial**: 3b earnings condor (selling event fear), Study 8
  VIX-cross straddles

## Where each component lives
| component | file |
|---|---|
| Constitution (8 hard rules, lines, receipts) | reports/PLAYBOOK.md |
| Sizing anchors + correlation clusters | docs/worst-loss-reference.json |
| Engine parameters (16Δ, 30-45 DTE, costs, CVaR) | src/otbt/config.py |
| Live signals + habitat + gates + tracker | pine/tj_scanner.pine |
| Test ledger (validated/buried/pending + kill bars) | docs/test-scoreboard.md |
| Receipts browser (per-ticker, per-indicator, IV) | dashboard/app.py |
| Data moat (IV series, cached pulls, trade tables) | data_cache/ + reports/*.csv |

## The measured edge (clean basis, 2 vendors, 13yr)
premium exists (IV > realized 63% of days) × gate selectivity (5.3× per-trade,
−94% drawdown) × tail control (21-DTE, anchors, clusters) × time.
Class: ~16-22%/yr at 1-lot discipline. Capacity at $48K: ~$800-1,500/mo.
$2K/mo consistent ⇒ ~$110-150K working equity at the same discipline.

## Verdict laws (how we decide anything)
Kill bars BEFORE runs · concentration check (top-5 share) · normalize-to-risk ·
full-depth only (never subsamples) · structural reason required for any
license/blacklist · the scoreboard is the memory.
