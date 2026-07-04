# Draft Playbook — what survived the gauntlet

*Generated 2026-07-04 from 25+ backtest runs, ~5,000 real-price trades, 6 futures
markets (2012–2025) + MSFT. All results net of realistic costs. Every line below
survived: real option prices, ALL signals included, honest cost model, and —
where marked D+1 — next-morning-9:30 execution (TJ's real workflow).*

## The five-column playbook (candidates)

| # | market | entry | structure | evidence ($/1-lot, D+1 where marked) | size guide (CVaR 7% of $48K) |
|---|--------|-------|-----------|--------------------------------------|------------------------------|
| 1 | **NG** | bb_2sd_call (upper 2-SD touch in downtrend) | short 16Δ call | **+$297/trade, 93% win, worst −$452 (D+1 ✅)** | worst MAE −$1.7K → 1–2 lots |
| 2 | **CL** | bb_2sd_call | short 16Δ call | +$126, 90% win (D+1 ✅) | MAE p95 −$2.4K → 1 lot |
| 3 | **CL** | five_day_low in uptrend | short 16Δ put | +$143, 85% win (D+1 ✅) but worst −$11.4K | tail breaches cap → 1 lot max, gate advised |
| 4 | **ES** | any with-trend put entry **+ 3-green gate** | short ~25Δ put | gated +$391, worst −$1,552 (D+1 ⚠️ untested) | 1 lot |
| 5 | **ES** | **gate-only** (no chart signal) | short put | +$308/trade, 91% win, 175 trades (D+1 ⚠️) | worst −$11.9K → 1 lot |
| 6 | **GC** | bb_2sd put in uptrend (+ gate → +$354) | short 16Δ put | +$321 same-day (D+1 ⚠️ untested) | worst −$1.4K → 1–2 lots |

**The 3-green gate (apply to everything):** sell only when the market's own IV
(a) rank ≥ 0.5 vs trailing year, (b) exceeds 20d realized (spread > 0),
(c) 5-day IV slope ≤ 0 (not still rising). Improved expectancy AND tails in all
4 markets tested. Never sell while vol is still expanding (the 25–35% IV
"kill zone" on CL held every catastrophic loss).

## Hard rules (all data-derived)

1. **Structure follows thesis.** Directional entry → directional structure.
   Strangles on directional entries lost in every test (−$160..−$341/trade).
2. **Align the sold side with the 10/100 trend** (H10 confirmed both directions,
   two markets). Never sell puts in downtrends or calls in uptrends.
3. **No tight dollar stops.** $100 stop cut MSFT P&L 70%; selling at −$1,500 MAE
   on CL doubled losses (−$27K → −$49.5K). Loss control = entry selection +
   21-DTE calendar + trend-invalidation, not stops.
4. **Rolling only on mean-reverting entries** (bb_2sd class: +$67→+$484/chain).
   Rolling five_day_low produced −$32K chains with −$48.6K MAE. Chain MAE is
   the sizing input if you roll.
5. **Size off worst MAE, not credit multiples.** 2×-credit sizing produced a
   19-lot position that could have hit −60% of the account.
6. **Blacklist:** NG puts (any timing), 6E anything (premium too lean),
   undirected strangles on single commodities (Tom-style: −$22K/13yr on CL),
   bb_20sma (marginal, worst tails).
7. **bounce_100ema: entry cut, exit kept.** No edge as entry anywhere ever
   (~$0 × 6 markets), but its 100-EMA invalidation is the best tail-control
   found — grafted onto other entries where thesis-relevant.

## Open items before trading any of this live

- D+1 test for ES puts / ES gate-only / GC (the un-lagged survivors).
- ES delta runs ~0.25 due to skew (measured, flagged) — decide target.
- Gated-conjunction n is ~180 across markets — grow via equity universe (~$30–50
  OPRA) before full confidence.
- Frequency check (H12): surviving methods ≈ 4–8 signals/mo across 6 markets at
  ~$150–300 avg → ballpark $800–1,500/mo at 1-lot discipline. Equities widen it.
- Paper-trade the playbook lines alongside live data before committing capital.

## What was definitively learned (see findings-ledger memory for detail)

Options selling pays the selective, small, mechanical seller: with-trend
premium at 2-SD stretches, gated by vol-state (rich+paid+stabilizing), managed
50%/21DTE, sized off worst-MAE. It confiscates from the indiscriminate: random
strangles, against-trend sales, tight stops, oversized rolls. The realized
edge is real but thin — and it lives in the conjunction of price structure AND
vol state, not in either alone.
