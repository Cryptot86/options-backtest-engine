# Allocation Spec v2 — handoff for implementation (2026-07-29)

*Supersedes the allocation portions of ALLOCATION_SIZING_SPEC.md. Source of
truth for values: docs/rulebook.json `_meta.allocation`. Written for another
agent/engineer to implement the live allocation + sizing layer.*

## 0. Core principle (proven, not opinion)
Capital protection first. **~25% of BPR to short premium is OPTIMAL, not
conservative** — the deployment frontier (full-book sim, 2015-2026) showed
25% BPR and 55% BPR make the SAME return (~6.2% CAGR) but 25% does it at 3% max
drawdown vs 7.1%. Deploying more = same return, 2.4x the pain. The book is
limited by SIGNAL QUALITY, not capital. **Never force deployment to hit a %.**

## 1. SGOV / cash collateral — DO NOT treat SGOV as a "position"
CRITICAL for the engine: **SGOV (or any T-bill ETF) is COLLATERAL + yield, NOT a
tracked strategy position.** It must NOT count against any allocation budget and
must NOT be blocked by dedupe/cluster/band rules.
- SGOV consumes ~25% of its value as BPR (empirical: 100 sh ≈ $10K -> $2,500 BPR).
- The other ~75% remains available buying power for selling options.
- It earns ~4.5% yield. It is where idle net-liq lives.
- RULE: buying/holding SGOV is always allowed; the allocation engine ignores it
  except to (a) reduce available BPR by 25% of SGOV value, (b) credit yield.
- Futures options (MES/MCL/MNG) need CASH margin (futures account) — SGOV can't
  collateralize those. Keep enough cash for the futures sleeves.

## 2. The allocation buckets (% of BPR / net-liq)
| bucket | budget | measure | notes |
|---|---|---|---|
| Equity-index selling (stock puts + MES) | 7% tail | worst-case | core earner; cluster=EQIDX |
| Energy selling (CL/NG calls) | 5% tail | worst-case | cluster=ENERGY; **often idle** |
| Metals selling (GC puts) | 5% tail | worst-case | cluster=METALS; **often idle** |
| — Total short-premium | **≤15% tail (~25% BPR)** | capped | structural: cannot reach 100% |
| Straddles (long vol) | 10% debit | max loss | hedges the sell book |
| Long calls (10x100 cross, ES/GC) | 5% debit | max loss | directional satellite |
| SGOV / cash | remainder | — | collateral + yield + futures margin |

**"Idle is normal."** Energy and metals fire only ~1-4 trades/yr each — those 5%
budgets will sit EMPTY most of the time. That is correct and expected. Do NOT
interpret an empty energy/metals allocation as under-deployment or a reason to
loosen anything. Deploy only when a gated/licensed signal actually fires.

## 3. DEDUPE spec (equity concentration control)
Applies to EQUITY (stock) puts only:
- **1 per name:** at most one open position per underlying at a time. If a name
  already has an open position, skip any new signal on it (bb_2sd AND
  five_day_low firing on the same stock = ONE trade, never two).
- **2 per day:** at most 2 NEW equity entries opened per calendar day. If 6 names
  fire on a market dip, take the first 2 that pass all gates, skip the rest with
  skip_reason='dedupe'.
- No sector rule: sector-diverse dedupe was TESTED (2026-07-29) and made ZERO
  difference (max-2/day already prevents same-sector same-day pairs). Not adopted.
- No hard equity %-cap: a hard equity tail-cap REDUCED MAR in testing; dedupe +
  the entry gate ARE the equity concentration control.

## 4. Sizing (per line)
`contracts = clamp(floor(0.02 * net_liq / stress_anchor), 1, abs_ceil)`
- Stress anchors / caps: rulebook.json `_meta.sizing_engine`. risk_pct=0.02, DO
  NOT raise (MAR peaks ~3% then falls).
- Never size off broker BPR — always the worst-loss/stress anchor.

## 5. Cluster tail caps (the real governor)
Before opening a position, sum the worst-case (contracts x anchor) of every OPEN
position in its cluster; new position must fit:
- EQIDX ≤ 7% of net-liq · ENERGY ≤ 5% · METALS ≤ 5% · TOTAL all clusters ≤ 12%.
- If it doesn't fit → skip, skip_reason='capacity'.

## 6. Entry gate (the crash protection — separate from allocation)
Stocks REQUIRE VIX 3-green (rank≥50 + IV>realized + 5d slope≤0). Index/energy/
metals futures are validated ungated. The gate is the crash protection (off in
expanding vol); the allocation band is NOT — a ~50% margin band is a vestigial
crisis buffer, mostly non-binding once cluster caps + dedupe are in place.

## 7. Exits (all lines)
50% of credit OR 21 DTE. No price stops. No trend-flip exit. No fast (30/40%)
exits (fast-TP tested: costs 27-41% of book profit).
