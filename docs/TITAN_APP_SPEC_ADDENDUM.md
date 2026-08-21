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
3b. **Align the undefined-risk/cluster cap to LAW: EQIDX = 7% of net-liq in
   WORST-CASE ANCHOR dollars** (app currently uses 8%). One cluster for ES/MES
   + NQ/MNQ + ALL gated stock puts (corr 0.93). ENERGY 5%, METALS 5%, total 12%.
   Anchor basis (worst vs p95) remains TJ's parked decision — implement both,
   config-switchable, default worst until he rules.
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
