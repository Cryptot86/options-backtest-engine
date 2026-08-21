# Titan App — Spec Addendum (2026-08-19)
*Supplements ALLOCATION_SPEC_V2.md + SIMULATOR_SPEC.md with laws adopted since,
plus corrections from the first live sessions. rulebook.json stays the value
source of truth. Every item below carries scoreboard receipts.*

## A. Rule-engine corrections (from the first live blocks, 2026-08-18)
1. **REMOVE the absolute-IV floor (NAME_IV_THIN / "IV < 35%") as a BLOCK.**
   Receipts: it would have blocked 63% of the licensed book (383 trades, 86%
   win, +$21,480). Demote to telemetry + optional priority-rank (IV>=35 cohort
   earns ~3x/trade — rank, never veto). The ONLY licensed pay check for stock
   entries is RELATIVE: chain IV > the stock's 20d realized vol.
2. **NO IV/vol check of any kind for futures lines** (ES/MES, CL/MCL, NG/MNG,
   GC/MGC — licensed ungated). Receipt: an IV>RV gate on MES would have blocked
   its BEST cohort (96% win, $53/tr, worst −$129). Show VIX-vs-RV as telemetry.
3. **Capacity/cluster overrides -> VIOLATION events, not conveniences.** If the
   owner-override survives at all: require a written reason, tag the trade
   forever, and surface a cumulative "override cohort P&L" report. The
   constitution itself has no overrides.
3b. **Align the undefined-risk/cluster cap to LAW: EQIDX = 7% of net-liq**
   (app currently uses 8%). One cluster for ES/MES + NQ/MNQ + ALL gated stock
   puts (corr 0.93). ENERGY 5%, METALS 5%, total 12%.
   **Anchor basis RULED 2026-08-21 (no config switch — pin it):**
   - Bucket/cluster accounting in **P95 anchors** (EQ put $367, MES $127,
     MCL $111, MNG $20, MGC $115).
   - Per-trade sizing stays on **WORST anchors** (EQ $3,495, MES $1,569, ...).
   Receipt: ledger audit docs/ledgers/ — p95 basis $44K→$111,349 (8.4%/6.0%DD,
   815 trades) vs worst-basis bucket-jam (445 trades, 5.1%). rulebook.json
   `CLUSTER_BASIS_LAW`. Capacity tiebreak when a bucket is full (~8 days per
   decade): admit highest IV−RV first, then alphabetical (convention).
4. **Theta alarm threshold = 0.10% of net-liq** (rulebook THETA_INVARIANT), not
   0.06%. Alarm/log only — never blocks, never sizes.

## B. Trade-lifecycle automation (the app knows the fills — automate what the
##    pine scanner does by manual input)
5. **21-day loss cooldown (LAW):** after a LOSING exit in a name, block new
   entries in THAT name for 21 calendar days from exit. Name-local. Wins clear
   immediately. Auto-derive from trade history.
6. **⚡ Fast-win window (HINT, never a gate):** after a win that hit 50% target
   in <=7 days, flag that symbol for 10 days: "fast-win window — best re-entry
   cohort (95%, n=21)". Display on new-signal screens; pay check still rules.
7. **The income loop:** on any 50%/21DTE exit, immediately free the dedupe slot
   and capacity; fresh trigger required for re-entry (never reuse a stale
   signal day).

## C. Whitelists & habitats (enforce; show receipts in the block message)
8. **Straddle whitelist:** ES/MES, CL/MCL (OVX gauge), + MSFT AAPL NVDA GOOGL
   AMZN META TSLA only. Census receipt: all other names −$21/tr (19/28
   negative). Stock straddle entries additionally require the NAME's own vol
   rank <=30 AND IV<RV (calm != cheap).
9. **Sell-call habitat:** CL/NG family ONLY (equity calls −$28/tr n=476;
   GC calls anti-diversification + adjacent graves).
10. **Ungated-futures list** (no vol checks, all other governors apply):
    ES/MES & GC/MGC puts (dip/5DL in uptrend), CL/MCL & NG/MNG calls
    (2-SD rally in downtrend).

## D. Telemetry already proving out (keep)
11. Emotion tag + reason-for-entry + planned target/exit at order time; skip
    logging for coverage integrity (all working as designed 2026-08-18).
12. SGOV: floating yield (verified 3.65% 2026-08; never hardcode); dividends
    ledger separate from position P/L in any income reporting.

## E. Backlog hooks (build-ready when data lands)
13. Strike-level chains purchase pending (ThetaData fallback ~\$80): unlocks
    7-study manifest; app should ingest chains to data_cache-compatible parquet.
14. MC cone view: equity curve inside the bootstrap cone (p5/p50/p95), kill
    lines at ~18-20% DD (options book) — "you are here" percentile.

## F. THE NUMBERS — hard deployment ceilings (answer permanently, at any equity E)
The app MUST display these live so the owner never has to compute them:
- EQIDX cluster (MES/MNQ + ALL stock puts): 0.07 x E in **P95-anchor dollars**
  (LAW 2026-08-21 — rulebook CLUSTER_BASIS_LAW; worst basis retired for buckets)
- ENERGY (MCL/MNG calls): 0.05 x E   |   METALS (MGC puts): 0.05 x E (p95 $)
- TOTAL across all clusters: 0.12 x E  <- THE CONSTITUTIONAL MAX, binds first
- SELL_BAND: 0.25 x E in BPR — outer fence only; a maximally-loaded legal book
  stays under it, so the band is structurally unreachable. There is NO
  VIX-conditional allocation (tested redundant: blocked $63.8K of good trades).
- Per-trade: 0.02 x E / line WORST-anchor (sizing keeps worst basis), per-line
  caps, 3 new equity/day.
- Reference at E=$44K (p95 buckets): EQIDX room $3,080 holds ~8 stock puts
  ($367 ea) or 2 MES ($254) + 7 stocks; TOTAL room $5,280. TJ's live 2 MES
  consume $254 of bucket — NOT $3,138 (that was the worst-basis jam, retired).

### F.1 CAPACITY DASHBOARD (build this view)
One screen, always visible: per-cluster bars [used anchor $ / budget $] +
total bar [used / 0.12E] + BPR bar [used / 0.25E] + open credit $. Color:
green <70%, amber 70-99%, red = full (entries auto-skip, logged). When the
owner asks "how much more can I sell?" the answer is THIS SCREEN, not a chat.
