# Scanner Automation Spec — Python port of tj_scanner.pine (for Titan)
*2026-08-19. Source of truth for LOGIC: pine/tj_scanner.pine (27 regression
laws) + rulebook.json for values. This spec ports the scanner to a nightly
Python service; Titan's existing rule engine (sizing/capacity/overrides) stays
downstream — the scanner emits SIGNAL STATE, Titan decides admission.*

## 0. Architecture
Nightly batch (after US close, ~4:30pm ET; optional 3:45pm preview run):
ingest EOD data -> compute per-symbol state -> emit JSON -> Titan consumes.
D+1 DISCIPLINE IS THE CONTRACT: tonight's confirmed close produces tomorrow's
actions. No intraday recompute, ever (law: signals act on confirmed bars).

## 1. Inputs (daily)
- OHLCV for: watchlist stocks (universe file), ES/MES, CL/MCL, NG/MNG, GC/MGC.
- VIX close, OVX close (CBOE). SPY close (for market RV).
- Earnings calendar (next-event date per stock; provider TBD — must cover the
  40-day horizon; UNKNOWN date -> earnUnk state, surfaced not silently passed).
- Trade history from Titan (fills + exits) -> cooldown & fast-win auto-derive.
- LIVE CHAIN IV (the full-automation enabler): at decision time, pull the
  ~40-DTE ATM IV per candidate stock via broker API (tastytrade API quote or
  equivalent). This automates the last manual step (light-3: chain IV > RV).
  Use ATM-tenor IV (matches the validated IVX basis), NOT the 16Δ wing IV
  (put skew would flatter the check). If the API pull fails -> state
  NEEDS_MANUAL_CHECK, never auto-pass.

## 2. Per-symbol computation (port EXACTLY; parity-test against pine)
- e10/e100 = EMA(close, span), pandas ewm(adjust=False) — matches pine ta.ema.
- trendUp = e10 > e100; freshCross = trendUp & !trendUp[1].
- BB(20, 2.0) on close; dip2SD = close <= lower & trendUp;
  low5 = close <= min(close[-5:])[shifted 1] & trendUp (PRIOR 5-day low);
  rally2SD = close >= upper & !trendUp (NG/CL family only).
- Stock RV (nRV) = stdev(log returns, 20) * sqrt(252) * 100.
- nRank = percentile rank of nRV vs trailing 252 obs (pine ta.percentrank
  parity: fraction of window STRICTLY below current, verify in tests).
- VIX gate: gRich = VIX 252d percentrank >= 50; gPaid = VIX > SPY 20d RV;
  gStable = VIX <= VIX[5]; gateGreen = all three.
- Name-gate (stocks, only when gateGreen == False): nRank >= 50 & nSlope
  (nRV - nRV[5]) <= 0 & no earnings in 40d & trigger fired & CHAIN IV > nRV
  (auto via broker pull, sec.1).
- Straddle light: whitelist ONLY (ES/MES, CL/MCL w/ OVX, 7 mega-caps);
  market gauge rank <= 30 & gauge < ref RV & (stocks) own nRank <= 30.
- Cooldown: last exit in symbol was a LOSS & exit_date within 21 cal days ->
  BLOCKED (auto from trade history). Fast-win: last exit was a WIN that hit
  50% target in <= 7 days & within 10 days -> HINT flag (never gates).
- Habitat whitelists identical to pine (RTY/ZB/SI/HG/FX = NO_GO with reasons).

## 3. Output contract (per symbol, JSON)
{ symbol, date, action: ACT_NOW|READY_NEEDS_PAY_CHECK|COOLDOWN|NO_GO|WAIT|
  HOLD, lights: {vix:[r,p,s], name:[rank,slope,earn,trigger]}, dials: {vix,
  vix_pct, vix_vs_rv, nrv, nrank, nslope}, pay_check: {chain_iv, rv, passed,
  source: api|manual|stale}, straddle: {whitelisted, cheap}, cooldown:
  {active, days_left}, fastwin: {active, days_left}, size: {anchor, cap,
  qty_at_equity}, receipts: short citation string }
Titan then applies: capacity/cluster -> dedupe -> size -> order ticket.

## 4. Acceptance tests (MUST pass before the pine is retired)
- PARITY: run both engines over the full history for 10 names + 4 futures;
  signal-day sets must match >= 99.5% (document every diff; timestamp/holiday
  conventions are the usual culprits).
- Known-truth anchors: RDDT golden cross 2026-06-03, death cross 2026-07-31;
  HD 5DL signals mid-Aug 2026; MES ACT_NOW 2026-08-19.
- The 27 pine regression laws get Python-test twins (same repo, same CI gate:
  no deploy on red).
- Cooldown/fast-win derived from a synthetic trade-history fixture (win-fast,
  win-slow, loss cases).
- Chain-IV pull: mock API failure -> asserts NEEDS_MANUAL_CHECK (never
  auto-pass).

## 5. Rollout (the few-weeks path)
Phase 1 (now): Python engine runs nightly IN SHADOW — emits states, Titan
displays both pine and python verdicts; log every divergence.
Phase 2 (2+ clean weeks, zero unexplained divergence): python becomes primary;
pine stays as visual chart companion (it is the UI, not the brain).
Phase 3: auto-ticket generation into Titan's PENDING_FILL with all checks
green — human still clicks send (the constitution keeps a human on the
trigger until a full quarter of shadow-parity + live agreement).

## 6. Explicitly NOT automated
- Order submission without human confirm (Phase 3+ decision, not now).
- Any override of capacity/cluster (no code path; violations only).
- Intraday anything. The engine is nightly by law, not by limitation.
