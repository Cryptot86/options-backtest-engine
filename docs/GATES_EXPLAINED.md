# Gates Explained — what every dot means, and why it exists

*Plain-language reference for the scanner's two gates. You do NOT need to memorize
this — the scanner IS the memory. Read it once to understand the principle, then
trust the lights. Code: `pine/tj_scanner.pine`. Receipts: `docs/test-scoreboard.md`.*

## The one principle behind every dot
Sell volatility **only when it is rich, you are overpaid for it, and it is not
expanding.** Every dot below checks one part of that sentence. When they disagree,
you don't sell. That's the whole system.

## VIX gate — 3 dots (the broad market, from SPY/VIX)
| dot | code | plain meaning | green when |
|---|---|---|---|
| 1 · **rich** | `vixRank >= 50` | VIX is expensive vs its own past year | IV percentile ≥ 50 |
| 2 · **paid** | `vix > hv20` | VIX is higher than what SPY actually moved (20d realized) | you're overpaid — that gap is the edge |
| 3 · **stable** | `vix <= vix[5]` | VIX today ≤ VIX five days ago | vol flat or falling — storm not building |

All three green = `gateGreen`. Stocks require it at signal close to enter.

## NAME gate — 4 dots (one specific stock, from its own price)
Used as a BACKUP when the broad VIX gate is shut, to let a specifically stormy
name through. It stands down the moment the VIX gate reopens.
| dot | code | plain meaning | green when |
|---|---|---|---|
| 1 · **rich** | `nRank >= 50` | this stock's realized vol is high vs its year | percentile ≥ 50 |
| 2 · **stable** | `nSlope <= 0` (`nRV - nRV[5]`) | its realized vol is flat/falling | slope ≤ 0 |
| 3 · **earnings** | earnings-in-window? | no earnings landmine | 🟢 clear · ⚪ verify · 🔴 blocked |
| 4 · **trigger** | `dip2SD[1]` or `low5[1]` | price actually dipped yesterday | 🟢 confirmed · 🕐 forming · 🔴 none |

## How the "expected IV" number is computed (and why it's manual)
The scanner (TradingView) can see **price but not the option chain**, so for a
single stock it computes the one side it can — **realized volatility**:
```
nRV = 20-day stdev of log returns × √252 × 100      (54.5% for CRWD)
```
That `nRV` IS the "expected IV" the row shows. It is NOT the option's IV — it is
the realized vol the option must BEAT. Before you enter, the row tells you to do
the one thing the script can't: **open the real chain and confirm chain IV > nRV.**
If chain IV > realized, you're being paid more than the stock actually moves —
that's the volatility risk premium, the entire edge. The VIX gate's "paid" dot is
this same test at the index level, where VIX is a published series so it's
automatic.

`CONVERGING — entry likely in ~K sessions`: if you type the chain IV you saw into
the `lastChainIV` input and it's currently BELOW realized (no edge yet), the
script projects how many calm sessions until realized vol decays down to it and
the trade becomes sellable.

## Do I need to remember any of this?
**No.** The gate is the externalized checklist — its whole purpose is so you don't
carry it in your head under pressure (which is exactly where human error creeps
in). The row tells you rich/paid/stable, blocks earnings, and hands you the one
number to verify. Understand the *principle* once; let the scanner remember the
*mechanics* every day. If you trust the principle, you'll trust the light.

## Every dot has a receipt (how it was built)
None of these are opinions — each survived the research campaign with a
pre-registered kill bar, tested across 35 names and 13 years, normalized to equal
risk. Kept only if it survived.
- **stable dot** — Study 2: every catastrophic trade lived in the rising-vol
  bucket; adding the slope light cut worst-case loss −$16,480 → −$3,490 (4.7×).
  This dot is the crash protection.
- **paid dot** — Study 6 measured true VRP per line (MES +3.24 pts, NG +9.14…);
  confirms the premium is actually there.
- **rich dot** — VRP is fattest when IV is high; forecast-vs-realized showed
  implied over-forecasts 63% of days.
- **VIX 3-green together** — validated at scale: 5-day-low $24 → $129/trade
  (5.3×), equity drawdown −94%.
- **name gate** — the second-best gate (~$62/tr) for when the broad gate is shut;
  a backup, which is why it stands down when the VIX gate reopens.
- **trigger dot** — the 2-SD-dip / 5-day-low price entry everything waits for.

The process: propose a dial → test across the fleet → set the kill bar before
looking → normalize to risk → keep only survivors. Seven survivors became seven
dots. The scanner is the compressed output of everything that didn't get buried —
so you don't have to remember it; the studies remembered it for you.
