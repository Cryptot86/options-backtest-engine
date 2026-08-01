# TJ's Stock (shares) Trading System — reference spec

*Provided verbatim-verified-from-code by TJ, 2026-07-31. This is the SHARE-trading
system, SEPARATE from the options premium-selling book this repo backtests. The
stock ENGINE lives in its own repo (parked on `feature/next-task` there); this
lab runs studies and hands verdicts back for TJ to promote/kill rules in that
engine. When TJ asks stock-trading questions, THIS is the model.*

## Signals
10×100 EMA golden cross (5-bar window) entry; death-cross exit; re-entry rules
("never miss the remount").

## Sizing — the part docs get wrong
**TSP proportional CORE sizing, NOT plain fixed-fractional:**
`Core_Equity = equity × TargetRisk% − open equity-at-risk`, then
position = 1% of core ÷ (2×ATR(14)), cash-capped, 10% clamp,
exits-before-entries.

## Allocation ("gearbox")
Buckets EQUITIES / CRYPTO / GOLD / ENERGY / BONDS, each with an EMA gate proxy
(SPY, BTC-USD, GLD, XLE, TLT), shared capital pool within a bucket, gates
ffilled.

## The 3 hard guardrails
1. Risk %
2. Bucket allocation
3. Sector-aware correlation blocks: 0.85 same-sector / 0.92 cross-sector /
   0.80 unknown

## Stop variants — QUESTION CLOSED (2026-08-01, 9 challengers buried)
**LAW: cross-only. No price stops of any kind. The death cross IS the stop;
TSP sizing carries the risk (Seykota: ride winners, cut losses, manage risk —
all three live in cross + sizing).** Receipts (scoreboard, exit-saga rows):
fixed 2/2.5/3×ATR negative at every age window and both remount speeds;
always-on chandelier −36% on majors; altitude-parachute fails every threshold
(n=1 carriers); vol-conditioning runs backwards; age-conditioning is ARM/RDDT
contamination; stop+reclaim package = NVDA-only luck; gaps (RDDT −21%) fill
through every stop identically. Realized single-name gap cost at TSP sizing:
~1.5% of equity — the sizing is the protection. OPEN (forward journal only):
chandelier 3×ATR on trades entered <2yr post-IPO — paper-track future young
IPO entries; adopt only if 10-15 untainted trades vote yes.

## Candidate rules to validate OOS in the stock engine
(Law in the options book does NOT auto-transfer — different holding mechanics,
different loss anatomy. "Guilty until proven innocent OOS.")
- 21-day name cooldown after a loss (options-book law, receipts in rulebook)
- After-win immediate re-tradeability
- TargetRisk 20% vs 100%
- Exit-type shootout

## Methodology guardrails
No lookahead; calendar-union + ffill (the −13%/+$65K bug is immortalized as the
warning); fees/slippage; walk-forward.

## Reference result — reproduction checksum
2007–2010: **+10.83% vs SPY −11.28%, max DD −6.5%.** Any reproduction of the
engine must verify against this before its output is trusted.
