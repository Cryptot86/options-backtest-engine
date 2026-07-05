# Six New Premium-Selling Candidates (research agent, 2026-07-05)

Ranked by evidence strength × orthogonality to the validated 2-SD/vol-gate family × daily-data testability. Full citations at bottom.

## 1. Term-Structure Carry Gate — "sell the front when the curve is steep"
- **Thesis:** the LEVEL of the IV term-structure slope (not our 5-day change dial) predicts short-dated option returns; steep contango = market overpaying for near-term insurance. Most-replicated option-return result in the literature (Vasquez JFQA; Johnson).
- **Entry:** per market, 30d & 90d constant-maturity ATM IV from our Black-76 settlement fits; enter when (IV30−IV90) percentile ≤ 20th (steep contango) AND 5-day IV change ≤ 0. ES cross-check: VIX/VIX3M ≤ 0.90.
- **Structure:** (a) naked 16Δ with-trend, 30 DTE; (b) vega-matched ATM calendar (short 30/long 90) — isolates the carry.
- **Exit:** (a) 50%/21DTE; (b) 25% of max value or 10 DTE on short leg; close if slope pctile > 50th.
- **Test first:** ES, GC. Failure mode: contango is ~80% of days → gate barely filters; calendar arm dies on double spreads.

## 2. Hedgers' Bid Harvest — COT hedging-pressure liquidity provision
- **Thesis:** commercial hedgers pay a measurable premium for the side they need; sellers providing liquidity earn it (~6.8%/mo pre-cost in Cheng-Tang-Yan). FLOW-based → fully orthogonal to our price/vol dials.
- **Entry:** weekly CFTC COT (free, lag 3 business days): commercial net-short percentile ≥ 80th (3yr) → sell the PUT side. Run unconditioned first to measure the factor, then intersect with our gate.
- **Structure:** naked 16Δ put 45 DTE (second arm 25Δ).
- **Exit:** 50%/21DTE; exit if COT percentile < 50th.
- **Test first:** CL, GC (never NG puts). Failure: published premium lives in strikes where spreads eat it; COT may proxy trend we already trade.

## 3. Crisis-Peak Fade — post-spike overreaction (the missing cell of our gate map)
- **Thesis:** biggest VRP is post-panic overshoot (Stein 1989; Poteshman; tastytrade "Fading Fear"). We tested "high & rising" (fails) and "mid & flat" (wins); the untested cell is EXTREME rank & confirmed peak.
- **Entry:** IV rank hit ≥ 0.90 within last 10 sessions AND IV closed lower 3 consecutive days from that high (ES extra: VIX/VIX3M back below 1.0). D+1. ~1–3 clusters/yr/market.
- **Structure:** DEFINED-RISK ONLY: 25Δ/5Δ put credit spread, 45 DTE. No naked, no calls.
- **Exit:** 50%/21DTE; hard stop if IV rank makes a new high; NO rolling.
- **Test first:** ES, CL. Failure: echo waves — RV stays elevated 30–90d post-spike. The 3-day-decline confirmation IS the trade; test 2d/5d variants.

## 4. NG Winter Vol-Cycle Decay — seasonal calendar-conditioned call selling
- **Entry:** Dec 1–Feb 15 only; RV<IV and front IV down ≥10% from trailing-30d high. One position at a time.
- **Structure:** 16Δ/5Δ call SPREAD (NG upside tails), 30–45 DTE.
- **Exit:** 50%/21DTE/trend-flip to uptrend.
- **Caveat:** only 13 winters — one Uri-type event dominates; forever suggestive, never conclusive.

## 5. Weekend Theta (Jones-Shemesh JF 2018) — test cheap, expect small
- Thursday close signal → enter Friday, exit Monday; short 30Δ strangle 7–14 DTE, ES only. Likely killed by costs — run gross first; proceed only if gross > 2× cost stack.

## 6. Skew-Richness Harvest — agent bets AGAINST it
- Sell 2× 16Δ puts / buy 1× 30Δ put when skew (IV16Δput − IVatm) ≥ 85th pctile + flat vol + uptrend. KNS (RFS 2013) self-refutes: variance-hedged skew premium ≈ 0 → likely our put edge in a costlier costume. BUT: build the skew-percentile DIAL regardless — may improve #1–#3.

## Test order: #3 (cheapest, all dials exist) → #1 naked arm → #2 (new COT pipe, highest orthogonality) → #4 → #5 gross-only → #6 dial-only.
**Shared trap:** all three top signals correlate with "vol was recently high" — run signal-overlap stats vs our composite gate before crediting new edge.

Sources: Vasquez (SSRN 1944298) · Johnson VIX term structure · CXO replication · Cheng-Tang-Yan (SSRN 3933070) · JBF demand-pressure · Jacobs-Li · Trolle-Schwartz (SSRN 1160195) · Stein 1989 JF · Poteshman (SSRN 262018) · Yan overreaction · tastytrade Fading Fear · Jones-Shemesh JF 2018 · Kozhan-Neuberger-Schneider RFS 2013 · Risk.net FX skew · arXiv 1506.05911 seasonal vol · CME NG weeklies · Moontower seasonal vol.
