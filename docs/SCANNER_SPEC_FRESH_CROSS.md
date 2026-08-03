# Fresh-Cross Scanner — spec for the Titan platform

*Handoff spec, 2026-08-02. Written to be implemented in the platform; a
reference universe file exists at `data_cache/universe_sp500.csv` (ticker,
sector, industry). No reference implementation was built by design.*

## 1. The problem this solves
The stock system's entry is the 10x100 golden cross (5-bar window), exits are
death-cross-only (NO price stops — law, 9 challengers buried), sizing is TSP.
Curated lists (IBD etc.) surface names only AFTER ~a year of outperformance —
by then the cross fired weeks/months ago, price sits far above the 100-EMA,
and the distance to the only exit makes the entry risk unacceptably large: the
system correctly refuses, and the theme is missed. Root cause: **lagging
curation used to time a leading signal.** Fix: scan the whole market DAILY for
the signal itself, so an entry can never be late; detect themes as clusters of
FRESH crosses (ignition stage) instead of clusters of high RS ratings
(narrative stage). Receipts: 6-mo RS at cross predicts outcome (leaders 46%
win / +32.2% avg vs laggards 32% / +8.1%, n=282) but 5/12 monster trades were
non-leaders — so RS RANKS attention, never vetoes a signal.

## 2. Inputs
- **Universe**: liquid US equities. v1 = S&P 500 (+ user-added rows: mid-caps,
  recent IPOs, personal names). Store as (ticker, sector, GICS sub-industry).
  Refresh constituents monthly; adding breadth (S&P 400/600) improves EARLY
  theme detection and is the preferred v2.
- **Prices**: daily adjusted closes, >= 14 months per ticker, plus SPY.
- **Cadence**: run nightly after the close. Weekly review is the human ritual.

## 3. Per-ticker computation (exact definitions)
```
e10   = EMA(close, span=10)        # exponential, adjust=False semantics
e100  = EMA(close, span=100)
up    = e10 > e100
cross = up AND NOT up[1]           # golden cross bar
fresh = any cross within last W bars          (W = 5, the model's entry window)
rs6m  = (close/close[126d ago] - 1) - (SPY/SPY[126d ago] - 1)   # RS vs market
ext   = close/e100 - 1             # extension above the 100-EMA
```
Skip tickers with < 160 daily bars (EMA warmup + RS lookback; young IPOs enter
the universe when they have history — note the young-IPO forward journal).

## 4. Outputs — two views
**A. FRESH CROSSES (the actionable list)** — all tickers with `fresh`, sorted
by `rs6m` descending. Columns: ticker, sector, sub-industry, cross date, age
(bars since cross), rs6m %, ext %, close. Persist daily (history of lists =
future OOS data for the RS-tiebreak rule).

**B. THEME IGNITION (the early detector)** — group ALL crosses of the last
`L = 20` bars by GICS sub-industry; any industry with **>= 2-3 crosses in the
window** is flagged IGNITING, with member tickers. This fires at the entry
stage — weeks-to-months before curated group-strength rankings.

## 5. Downstream decision rules (already law — the scanner never overrides)
1. Entry ONLY via the model's cross + 5-bar window. The scanner finds; the
   model fires. Nothing on any list is ever bought directly.
2. Simultaneous valid crosses in one theme: correlation blocks fire first
   (0.85 same-sector); among survivors, **higher rs6m wins** (leader-first —
   in-sample receipt; log outcomes as the forward journal).
3. `ext` is the chase-guard: at a fresh cross ext is naturally small; if a
   name is noticed late (ext large), the answer is NO — misses are free,
   chases are not (no-stop system: ext ~= distance to the only exit).
4. TSP sizing unchanged; hot high-ATR names auto-size smaller.

## 6. Parameters (defaults + why)
| param | default | rationale |
|---|---|---|
| W (fresh window) | 5 bars | = the model's entry window |
| RS lookback | 126 bars (6mo) | tested gradient (4x leaders/laggards) |
| L (ignition lookback) | 20 bars | ~1 month; theme = burst of crosses |
| ignition threshold | 2-3 names/industry | 3+ = strong theme; 2 = watch |
| min history | 160 bars | EMA warmup + RS lookback |

## 7. Acceptance tests for the platform build
- RDDT: golden cross detected 2026-06-03 window; death cross 2026-07-31.
- A name crossing 6+ bars ago must NOT appear in view A (but counts in B).
- rs6m must match manual calc within rounding on 3 spot-checked names.
- Deleting SPY data must fail loudly (RS is relative — never silently absolute).
- Industry with 3 crosses inside L must appear in view B with all members.

## 8. Explicitly out of scope
No buy signals, no stops (law), no RS veto of valid crosses, no fundamental
data. The scanner changes what is SEEN, never what is TRADED.
