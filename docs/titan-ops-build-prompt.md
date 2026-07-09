# Titan Ops — build prompt (final, 2026-07-06)

Build an options-trading operations module ("Titan Ops") on top of my existing app tradewithtitan.

MY STACK: [describe your existing tradewithtitan stack — frontend, backend, DB, auth — or say "greenfield, choose sensible defaults"]
MODE: Single user (me) for v1. Paper-trading mode FIRST — every trade flagged paper/live. No broker integration, no auto-execution, no customer features in v1.

== CONTEXT ==
I run a systematic options book validated by 13 years of backtests. The app's job is NOT signal generation (that comes from my Python scanner + TradingView) — its job is DISCIPLINE ENFORCEMENT and RECORD-KEEPING: journal every trade, show my allocation state, enforce my rules at entry time, and grade my process. Core principle: I am the biggest risk to my own system; the app exists to make rule-breaking visible and rule-following effortless.

== DATA MODEL ==
- accounts: id, name, mode(paper|live), starting_equity, current_equity
- signals: id, signal_date, symbol, line, direction, source(scanner|manual),
  status(pending|entered|skipped|expired), skip_reason(capacity|dedupe|gate|habitat|manual)
- trades: id, signal_id, account_id, mode(paper|live), symbol, line,
  structure(short_put|short_call|long_call|shares|straddle),
  legs JSON [{side, type, strike, expiry, qty, fill_price, mid_at_fill}],
  entry_date, exit_date, strike (display strike for single-leg; primary strike for multi),
  credit_received / debit_paid (net, after fees),
  spot_at_entry, spot_at_exit,
  margin_used,
  vol_context JSON (frozen at entry: vix, vix_band, market_gauge_reading, gate_state),
  pnl (net of fees), days_held, exit_reason(tp_50|t_21dte|trend_flip|straddle_tp|straddle_sl|expiry|MANUAL_OVERRIDE),
  max_drawdown_seen, emotion_tag(calm|fomo|fear|revenge|confident) REQUIRED at entry,
  rule_adherent BOOLEAN at exit, notes, lesson
  — rows are APPEND-ONLY; corrections are new annotations, never edits.
- daily_snapshots: date, account_id, equity, open_positions_marks JSON,
  sell_bucket_used, sell_bucket_cap, buy_bucket_used, buy_bucket_cap, vix, vix_band,
  gate_state per market (ES, stocks, CL, NG, GC)
  — one row per day; this table powers the equity curve, max drawdown, and MAR.
- process_scores: week, signals_taken, signals_skipped_valid, signals_missed,
  exits_per_rules, manual_overrides, score_pct

== TRADE ENTRY FORM (critical: match my review format) ==
The entry flow and the journal list view MUST present trades in this exact column
order — it is the format I already use for every performance review:

| symbol | signal_type (line) | entry_date | exit_date | strike | pnl | days_held | exit_reason |

At ENTRY the user fills: symbol, line (picker), entry_date (default today),
strike(s)/legs, credit-or-debit, spot_at_entry (prefill from quote if available),
margin_used, emotion_tag (required, 2-tap UI). exit fields stay empty.
At EXIT the user fills: exit_date, exit price, exit_reason (picker), rule_adherent.
pnl and days_held are COMPUTED, never typed.
Everything else (vol_context, snapshots) is captured automatically — the human
types as little as possible; the app never asks for what it can compute.

== RULES ENGINE (hard-code; validated law) ==
LINES:
1. SELL PUT (16Δ, 30-45 DTE): stocks require gate GREEN; ES/MES futures ungated.
   Entry always D+1 (signal yesterday → enter today ~9:30am).
2. SELL CALL (16Δ): ONLY NG and CL futures. Hard-block on stocks with explanation.
3. TREND RIDE: shares or long call at 10x100 EMA bullish cross; exit ONLY on trend
   flip, never a profit target.
4. STRADDLE (long vol): only when that market's own gauge reads cheap;
   ES 60-90 DTE, CL 40-60 DTE, stocks ~40 DTE; exits +50%/−40% of debit / 21 DTE.
ALLOCATION (VIX-banded, % of current equity, SELLING bucket): VIX<25 → 25%;
25-35 → 50%; 35+ → 60% (never 100%). BUYING bucket: 15% flat.
Block entries exceeding a bucket; render "SKIP — capacity" as a correct outcome,
celebrated not hidden, and write the skipped-signal row.
POSITION SIZING (hard requirements — enforce at trade creation, not advisory):
1. BUY-SIDE CEILING MONITOR: total debit tied up in ALL long-option positions
   (trend-model calls, straddles) may NEVER exceed 15% of current equity.
   Pre-trade check blocks any entry that would breach it; a persistent meter
   shows usage and turns amber at 12% (warning) — this is a monitored limit,
   not a guideline. Trend-model BUY CALL signals that don't fit -> logged as
   skipped(capacity), never squeezed in.
2. PER-POSITION 2% MAX-LOSS SIZING: each stock position must be sized so its
   worst-case loss <= 2% of current equity.
   - Long options/spreads: max loss = debit -> debit <= 2% of equity.
   - Shares (trend rides): share count = (2% of equity) / stop-distance
     (entry price minus trend-invalidation level).
   - Short premium: use the line's historical worst loss per contract (from
     the backtest reference table I will provide) as the max-loss estimate;
     contracts sized so that estimate <= 2% of equity. Tom's 5-7% undefined-
     risk cap remains the OUTER bound; 2% is the per-name target.
   The entry form COMPUTES the allowed size and pre-fills it; typing a bigger
   size requires an explicit override note (flagged in process score).
3. GAP CLAMP (single-name shares): stop-distance sizing alone is unsafe on
   equities (fresh trend cross = tiny stop = huge authorized notional, and
   stocks GAP through stops). Additional hard cap: single-name share notional
   <= 10% of current equity. Apply min(2%-rule size, gap-clamp size); show
   which clamp bound. Futures keep pure stop-based sizing.
HARD RULES at trade creation:
- DEDUPE: same symbol + same signal_date = ONE trade max (block, log the skip).
- Capacity-conflict hint: NEW symbol beats re-entry in a held symbol
  ("diversify first, deepen second").
- NO STOP-LOSSES on short premium. A manual early exit requires a note and is
  flagged exit_reason=MANUAL_OVERRIDE (hits the process score, permanently).
- Exits: short premium at 50% of credit OR 21 DTE, whichever first. Countdown shown.
- SKIPPED SIGNALS ARE ROWS TOO: every signal gets a journal outcome
  (entered or skipped+reason) — coverage integrity, no silent gaps.

== SCREENS ==
1. TODAY (home): yesterday's signals due for entry this morning (D+1 workflow),
   each GO/BLOCKED with the reason (gate red, capacity, dedupe, habitat).
   VIX band + both bucket meters. Positions needing action (21-DTE due,
   trend-flip, 50% target likely).
2. POSITIONS: open trades — days held, DTE countdown, cushion (spot vs strike, pts
   and %), exit rule per line. Anti-panic UX: an underwater position shows
   "worst historical drawdown for this line survived and recovered: [reference
   table I will provide]" instead of alarm styling.
3. JOURNAL: the table above, filterable by line/symbol/month/mode/rule_adherent;
   row detail shows legs, vol_context, emotion, lesson. Monthly roll-up view:
   month | P&L booked | trades entered | trades exited | planted-vs-booked note.
4. ANALYTICS (all computable from journal + daily_snapshots alone):
   monthly P&L table; win% and $/trade BY LINE; equity curve with max-drawdown
   band (reference line at −8%, my backtest maxDD); MAR; per-name dispersion;
   exit-reason split; capacity-skip rate; slippage report (fill vs mid_at_fill,
   cumulative — answers "is live capture ≥ 2/3 of backtest?"); regime buckets
   (P&L by vol_context at entry). Centerpiece: WEEKLY PROCESS SCORE — % of
   signals correctly acted on and exits per rules. A 100%-process losing week
   must visually outrank a rule-breaking winning week.
5. RULES: static playbook reference (content provided), habitat table
   (what trades where), and the graveyard (banned strategies with the dollar
   cost of each lesson).

== DESIGN INTENT ==
Calm, not casino. No flashing reds, no confetti. Tone: a co-pilot that says
"the rules have this handled." Numbers in tabular monospace. Daily-settlement
granularity only — deliberately NO intraday P&L feed (it is an emotion machine;
this app exists to be the opposite). Mobile-usable at 9:30am.

== BUILD ORDER ==
1. Schema + rules engine, unit tests for every hard rule (dedupe, capacity,
   habitat, exit computation, append-only journal)
2. Today screen + trade entry flow (the daily loop, in my table format)
3. Positions + Journal (+ monthly roll-up)
4. daily_snapshots job + Analytics + process score
5. Rules reference page
Ask me for: stack details, playbook content, the drawdown reference table,
and gauge/gate feed format when you reach those steps.

== FUTURE DIAL (record from day one, activate after validation) ==
Per-name IV three-dial treatment (TJ, 2026-07-09): the name-richness check is
currently LEVEL-only (IV >= ~35% / IV > own RV). The name's IV *slope* likely
matters for the same reason VIX slope does (rich-and-rising = name-level
crisis-in-progress). We lack per-name IV history to test it. Therefore: the
app/scanner must SNAPSHOT every watched name's ATM IV daily from day one
(tastytrade API), building the series for free. Once ~6 months exist, test
slope as a 5th filter; until then, earnings-date check + market slope cover
most rising-name-IV cases. Interim entry checklist stays: gate green + signal
+ name IV >= 35% + no earnings inside DTE window.

== STRADDLE SLEEVE — CONTROL-CENTER RULES (per portfolio) ==
Habitat (hard-block elsewhere): ES/MES (60-90 DTE), CL/MCL (40-60 DTE),
liquid large-cap stocks (~40-45 DTE). BANNED: GC, NG (-$14.7K in test —
carry-market calm persists). Entry ONLY on the cheap-vol light (own-market
gauge pctile <= 30 AND IV < realized) — snapshot the light state into the
trade row.
Exits, first-hit-wins: TP at +50% of debit | SL at -40% of debit | 21 DTE
remaining. SET EXPECTATIONS IN THE UI: in testing only ~28% of straddles
reached +50%; 72% exited on the calendar (median hold ~18-21d) and the line
still earned +$281-341/trade — show "time exit is the normal outcome" on the
position card so the user doesn't read a non-TP exit as failure. Note the SL
exists here (unlike short premium) because long premium bleeds theta — it's
a bleed circuit-breaker, not a panic exit.

== HABITAT REGISTRY UPDATE (2026-07-09, applies to rules engine + journal) ==
RTY/M2K (Russell 2000): TESTED AND REJECTED — hard-block in the rules engine
with reason "tested: real but dominated (1/3 of ES expectancy, W/L 0.35,
worst -$5.6K/contract; call side toxic — squeeze index)". Distinct from
"untested": the block message must say WHICH it is; the journal's skip_reason
gains value "habitat_rejected" (vs "habitat_untested"). Current registry:
- Puts: ES/MES (ungated), GC/MGC (ungated), stocks/ADRs (gate + name-IV>=35%
  + no earnings in window; basket = user judgment, class-validated)
- Calls: NG, CL only. ZB = paper-trade candidate (thin n=33). RTY = rejected.
- Straddles: ES/MES 60-90 DTE, CL/MCL 40-60, liquid large-caps ~40-45;
  GC/NG banned.
- Trend rides: ES/GC micros + stocks (shares primary, gap clamp 10%).
