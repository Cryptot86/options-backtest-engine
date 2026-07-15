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

---

# PORTFOLIO ALLOCATION MODEL (validated 2026-07-05, "Toyota" config)

Simulated on real trade history 2019-07 -> 2025-06, $50K start, compounding,
capacity-enforced (margin est.), VIX-banded:

| VIX regime | % equity for SELLING | % for BUYING |
|-----------|---------------------|--------------|
| < 25      | **25%**             | 15%          |
| 25–35     | **50%**             | 15%          |
| 35+       | **60%** (never 100%)| 15%          |

Book: top-15 gated equities (1-lot) + MES puts (micro ES) + CL/NG bb_2sd calls
(1-lot) + micro ES/GC long calls on crosses.

**Result: $50K -> $74.3K (+49%, 6.8% CAGR), max drawdown -8.1%, worst year
-3.0%, MAR 0.85.** User's draft bands (35/40/60) gave same return with -12% DD
-> adopted 25/50/60. Sweep showed: less in calm markets, more in the 25-35 VIX
band (the gate's sweet spot). ~20% of signals skipped by capacity = discipline
by design.

---

# OUT-OF-SAMPLE VALIDATION (Jul 2025 - Jun 2026, rules frozen on data <= 2025-06)

**PASS.** 72 trades, 86% win (identical to in-sample), +$2,711 raw; with the
playbook's own concurrency rules enforced (one position per name — bb_2sd and
five_day_low firing together on the same stock = ONE trade; max 2 new equity
entries/day): **+$6,778 (~$565/mo), worst month -$5,370.**

Per line OOS: MES puts +$4,554 | NG calls +$1,504 | CL calls +$366 | long call
+$705 | equities -$350 (rules-enforced; raw -$4,418 was one stock, META,
double-entered on one day losing -$9,041 combined).

**NEW HARD RULE (learned OOS): dedupe same-name same-day signals — multiple
triggers on one underlying = one position, never stacked.**

## Cluster-risk resolution (2026-07-06, swept incl. OOS year)
Equity-sleeve caps (30-60% of selling capacity) tested vs uncapped, all with
same-name dedupe enforced: caps REDUCE MAR (0.75-0.82 vs 0.91) without
improving worst-month (~-4.9% at every level). **Verdict: the dedupe rule IS
the cluster fix; no equity cap needed.** 7yr incl OOS: $50K -> $81,090
(7.2% CAGR, maxDD -7.8%, MAR 0.91) — best configuration found to date.

## LONG-VOL SLEEVE ADMITTED (book strategy, tested 2026-07-06, 11 instruments)
**Buy ATM ~40DTE straddle when vol is CHEAP** (own-IV rank<=0.3 & IV<RV for
futures; VIX equivalents for stocks), exits +50%/-40%/21DTE. Habitat: ES, CL,
liquid stocks — pooled 121 trades, +$281/trade, +$33,947. NEVER on GC/NG
(cheap carry-market vol stays cheap: -$14.7K combined). Hybrid (cross+cheap)
arm KILLED (2-for-13 ex-ES). Role: positive-carry crash insurance
complementing the short-premium sleeves. Paper-trade with the rest.

## H14 CLOSED — calendars rejected (2026-07-06); charter fully adjudicated
Calendars (sell 30DTE/buy 90DTE ATM put, cheap-vol entries): futures KILLED
(-$20.4K/142: ES -$287, CL -$243, GC control -$79 — movement destroys the
short front leg); stocks marginal (+$34/tr x35, pinners +, movers -) — below
deployment threshold. THE LESSON: TJ's cheap-vol timing instinct was RIGHT;
the straddle is the correct vehicle for it (+$281/trade on identical days).
All fourteen charter hypotheses (H1-H14) now tested and ruled.

## FINAL PORTFOLIO CONFIG (2026-07-06): straddle sleeve folded in
Sleeve 3 (micro straddles: MES/MCL + stocks, cheap-vol entries, 21d spacing)
added to the buy bucket: 7yr $50K -> **$93,625 (9.4% CAGR, maxDD -8.0%,
MAR 1.17)** vs 0.91 without. Buy-cap sweep 15/20/25%: identical (bucket never
binds) -> **15% stays**. Sleeve is episodic: zero entries Jul-2024..Jun-2026
(no cheap-vol days) — judge it by regimes, not quarters.

## Sleeve-3 DTE spec (swept 2026-07-06)
ES: 60-90 DTE (monotonic: 40->+$60, 60->+$400, 90->+$675/tr, win% 41->53 —
equity vol storms need runway). CL: 40-60 DTE only (peaks at 60 +$129; 90 DTE
-$230 — crude spikes round-trip inside a quarter). Micro sizing mandatory
(90-DTE ES worst -$8.5K full-size -> MES -$850).

## Put-ratio 1x2 test (2026-07-07): GC upgrade candidate, ES declined
Buy ~30D / sell 2x 16D, same signals D+1, 50%-credit/21DTE: ES +$316x537
(worst -$13.0K) vs single put +$396x439 (worst -$15.7K) -> single put stays
(simpler, richer; micros handle the tail). GC: ratio +$108x149 worst -$1,760
vs single +$143x277 worst -$8,232 -> **tail cut 78% for 24% expectancy: ratio
is the better GC line by MAR. Status: candidate — confirm 3-leg slippage in
paper before law.** Forecast miss logged: the long leg's crash cushion beat
the second short's tail add — structure was put-spread + naked, not 2x naked.

## ZB (30yr T-bond) tested (2026-07-07): puts REJECTED, calls candidate
Put-selling all lines negative (-$34/tr x475, worst -$4,517): bond IV ~10%
pays pennies vs rate-shock dollars; 2022-24 bear faked out the trend filter.
Forecast miss logged (predicted ES/GC-like). bb_2sd_call: +$152 x33, 91% win,
worst -$673 — same fade-the-hope-rally physics as NG/CL; thin n -> paper-trade
candidate only. ZB does NOT enter the put book.

## NAME-LEVEL RICHNESS CHECK (TJ+Tom, tested offline 2026-07-08) — checklist rule
On gated equity entries, the NAME must also pay: entry IV >= ~35% (Tom's
threshold; tasty-chain glance at entry) or IV above the stock's own 20d RV.
Evidence (39 gated trades w/ IV): rich kept 18 -> +$203/tr, 100% win, worst
+$22; quiet dropped 21 -> -$103/tr incl the book's only -$4.5K disaster.
Day-matched same-regime cross-section confirms (+$112 vs -$240). THIN SAMPLE
-> checklist rule for paper, promote to law if live agrees. Delivery: manual
at entry / Python scanner — NOT Pine (no options data there).

## POSITION SIZING LAW (TJ, 2026-07-08)
1. Buy-side ceiling: ALL long-option debit combined <= 15% of equity — hard
   monitored limit (amber at 12%); unfitting buy signals = skipped(capacity).
2. Per-position 2% max-loss: every stock position sized so worst case <= 2%
   of equity (long: debit; shares: 2% / stop-distance; short premium: line's
   historical worst loss per contract as the estimate). Tom's 5-7% undefined
   cap = outer bound; 2% = per-name target.

## GAP CLAMP amendment (2026-07-08, found via live LYFT sizing)
Stop-distance sizing alone is unsafe on single names: a fresh cross = tiny
stop = huge authorized notional, but equities GAP through stops. Second
clamp: **single-name share notional <= 10% of equity** (20% gap x 10% = the
2% law preserved under stress). Futures keep pure stop-based sizing
(continuous session). Example: LYFT 7/8: formula said 1,978 sh ($30K);
clamped answer 330 sh ($5K).

## RTY tested (2026-07-09): real edge, NOT licensed (dominated by ES)
Puts: five_day_low +$103x198 (79%), bb_2sd +$102x39 — a THIRD of ES's rate
with W/L 0.35 (winners ~$550, losers ~$1,500-2,250) and worst -$5.6K/contract.
Calls: ALL negative (squeeze index — bear rallies don't fade; same physics
as stock call-selling). Verdict: correlated ~0.9 with ES, pays 1/3 as much,
tails worse -> every RTY slot is a worse ES slot. Whitelist stays ES/MES.
Revisit only when capital saturates ES capacity.

## Covered-PEAD final verdict (2026-07-11, split-corrected + benchmarked)
Beat-arm (buy shares + sell ~30d call D+1 after an earnings BEAT, ~25 DTE to
expiry): +$639/tr x99 vs +$171 shares-only — the OPTION LEG added +$469/tr
(post-earnings premium harvest, hedged; NOT beta). Miss-arm: killed (-$172).
STATUS: PARKED CANDIDATE — capital-heavy ($20-45K/position; fits the $350K
trend book better than the $50K options account), 5 mega-caps, one era.
Spread-PEAD remains killed (-$188/tr corrected). Vol-ramp: breakeven, killed.

## NAME-GATE PATHWAY (TJ's hypothesis, tested 2026-07-14) — candidate line
Single-name vol storm cresting while VIX flat: on VIX-gate-CLOSED days, take
the dip/5DL signal IF the NAME's own dials are green: RV pctile >= 50 AND RV
5d slope <= 0 AND (at entry, from the chain) IV > the name's RV.
Evidence: 89 trades across 8 yrs / 11 of 13 names positive: 87% win, +$67/tr,
worst -$2,796 — vs the +$9/tr, -$18K wasteland it filters. Max 2 entries/day
(name storms don't cluster — smooths deal flow between market-gate windows).
The IV>RV light is LOAD-BEARING (without it: +$38/tr, worst -$13,248) ->
delivery = Pine shows 2 price lights + displayed RV; human completes light 3
on the chain. STATUS: candidate — paper-trade alongside the book; scanner
implements all 3 lights natively; promote after live sample.
NAME-GATE sweep addendum (2026-07-14): 3x3 parameter sweep (rank 40/50/60 x
slope 3/5/7d, IV>RV held) = FULL PLATEAU, all cells +$40..+$106/tr, chosen
(50,5d) mid-plateau. Time-split both halves positive. Remaining gaps: no true
OOS (rule designed on full data) + search multiplicity -> candidate until
~20-30 live/paper entries confirm.

## Treasury curve + silver verdicts (2026-07-14)
ZN (10yr): REJECTED both sides (puts all negative, IV 5.4% pennies-vs-tails;
calls n=3 noise). ZT (2yr): REJECTED — avg credit $7, IV 1.6%: no premium
exists to sell. Treasury family: only ZB 2SD-rally calls remain (paper cand).
SI (silver): SPLIT — bb_2sd puts CANDIDATE (+$413/tr x35, 89%, worst -$2,651;
better than GC per-trade, thin n) · five_day_low puts REJECTED (-$57, worst
-$8.3K: squeeze grinds) · ALL calls REJECTED (worst -$13.7K — squeeze metal).
First market where the two put entries disagree. SI stays OFF Pine signals;
bb_2sd entries = manual/journal candidate like ZB calls.
