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
| 4 | **ES** | any with-trend put entry **+ 3-green gate** | short ~25Δ put | gated +$391, worst −$1,552; underlying entries D+1 ✅ (ES all methods positive at D+1, run 29) | 1 lot |
| 5 | **ES** | **gate-only** (no chart signal) | short put | +$308/trade, 91% win, 175 trades; entry basis D+1-robust on ES ✅ | worst −$11.9K → 1 lot |
| 6 | **GC** | bb_2sd put in uptrend (+ gate → +$354) | short 16Δ put | +$303 at D+1 ✅ (run 30, essentially unchanged from +$321) | worst −$1.4K → 1–2 lots |

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

## D+1 final validation (2026-07-05)
ES run 29: five_day_low +$333, bb_20sma +$328, bb_2sd +$197 — all positive at D+1.
GC run 30: bb_2sd +$303, bb_20sma +$315 — unchanged/improved at D+1.
Only D+1 casualty project-wide: CL bb_2sd puts. Playbook is execution-validated.

---

# Research Pipeline — next edges to test (agent findings, 2026-07-05)

Full specs + citations: reports/NEW_STRATEGY_CANDIDATES.md. Ranked by evidence × orthogonality × testability.

## Tier 1 — test first
1. **Crisis-Peak Fade** — sell 25Δ/5Δ put credit spreads AFTER extreme vol confirms its peak (IV rank hit ≥0.90 in last 10 sessions AND 3 straight down-days in IV). Completes our gate map's missing cell. All dials already built.
2. **Term-Structure Carry** — sell 30-DTE premium when the IV curve is in steep contango (IV30−IV90 pctile ≤ 20th) and not expanding. Strongest published evidence (Vasquez JFQA; Johnson).
3. **Hedgers' Bid Harvest** — sell the put side when CFTC commercial hedging pressure is extreme (COT net-short ≥ 80th pctile). Flow-based → most orthogonal to everything we trade. Needs one free data pipe (COT).

## Tier 2 — cheap to run, capped expectations
4. **NG Winter Vol Decay** — Dec–Feb call spreads as winter fear resolves (only 13 winters of data; forever suggestive).
5. **Weekend Theta** — Friday→Monday short strangles on ES (JF 2018 evidence; likely dies to costs — gross test only).

## Bet-against (build the dial, skip the trade)
6. **Skew-Richness ratio spreads** — academically self-refuting once variance-hedged; but ADD the skew-percentile dial to the panel.

## Long-side sleeve (validated 2026-07-05, run 33)
**Buy ATM call on fresh 10×100 bullish cross (D+1)** — ES +$1,248/trade (n=29), GC +$368; capped-loss/positive-skew complement to the short-premium sleeves. Regime-dependent (bull-era result); user's own live strategy, independently confirmed. Avoid on CL/NG.

## Simple cross rules (validated, run 31)
- Fresh bullish 10×100 cross → sell 16Δ put: ES +$222, GC +$299, CL +$179 (D+1). ~3/yr/market.
- Fresh bearish cross → sell call: BLACKLISTED (relief bounce, −$244 pooled).

---

# CAPSTONE (2026-07-05): the gate is settled law

**31-equity validation (4,364 trades, 2019-2025):** VIX 3-green gate flips the
pooled book from −$21/trade (−$81.5K total, worst −$22.4K) to **+$88/trade
(+$44.2K total, worst −$5.8K)**. Every method improves. VIX-rank top quartile
worst bucket (crisis-in-progress) — identical physics to futures.

**Rule: NEVER sell ungated.** Combined evidence: 4 futures markets (own-IV
dials) + 31 equities (VIX dials), ~680 gated trades, uniform direction.

**New edge admitted — Term-Structure Carry (run: ES +$317 x130, GC +$91 x144,
85% win):** sell with-trend 16Δ when (IV40−IV90) percentile ≤ 20th and vol not
expanding. PENDING: overlap check vs 3-green gate, CL series rebuild.

**Killed: Crisis-Peak Fade** (−$162/trade pooled; echo waves — IV down 3 days
after a 0.90-rank spike is not a confirmed peak). Gate map complete: only
moderately-rich-and-stable premium pays.

**Equity suite status: 31/35 names complete ($50 budget), CRM/ORCL/INTC/MU
skipped by user decision. Signal delivery requirement: finalized rules ship as
Python scanner / Pine (price half only) / tradewithtitan (full gate).**
