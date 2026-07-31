# tradewithtitan — options backtest lab

TJ's systematic trading research lab. Two systems, one doctrine:
1. **Options premium-selling book** (this repo's subject) — sell 16Δ, 30-45 DTE,
   exit 50% credit or 21 DTE, no price stops, VIX 3-green entry gate.
2. **Stock (shares) system** — separate engine in its own repo; spec in
   `docs/STOCK_SYSTEM.md`. Read that file before answering any stock question.

## Read these before proposing anything
- `docs/rulebook.json` — machine-readable LAW (lines, sizing, allocation,
  cooldown, theta invariant). Source of truth for all values.
- `docs/test-scoreboard.md` — living ledger of every study: validated / closed /
  buried, with receipts. **TJ's standing rule: update it every time a study
  opens, closes, or changes status.** Answer "did we test X?" from here.
- `reports/PLAYBOOK.md` — human law + the why behind each rule.
- `docs/ALLOCATION_SPEC_V2.md`, `docs/SIMULATOR_SPEC.md` — app handoff specs.
- `docs/GATES_EXPLAINED.md` — what every gate dot means + study receipts.
- `docs/worst-loss-reference.json` — sizing anchors + correlation clusters.
- `pine/tj_scanner.pine` — the live scanner. After ANY edit run
  `python3 .claude/skills/pine-regression/check_pine.py --all` (or /pine-regression);
  do not commit pine changes while it fails. Add a law there for every bug fixed.

## Doctrine (non-negotiable)
- Kill bars are pre-registered BEFORE a study runs. Post-hoc rules must survive
  OOS on unseen data or they die ("guilty until proven innocent OOS").
- Before any verdict: concentration check (top-5 share) + normalize to risk.
- MAR (CAGR/maxDD) is the score. Win% is a vanity metric.
- Sizing: `qty = clamp(floor(0.02·equity/worst_anchor), 1, cap)` — never off
  broker BPR. Do NOT raise risk_pct (MAR peaks ~3%, falls after).
- NEVER encourage sizing up, leverage, or income-dependence on the account.
  Capital protection first — Toyota, not Ferrari.
- D+1 discipline: signals act on YESTERDAY's confirmed close, never intraday.
- Data: IVol subscription CANCELLED (403). `data_cache/` (IV series, option
  pulls) is the permanent lab — studies run $0 from owned data.
- `.env` is gitignored; never print API keys.

## Environment
- Python: use `.venv/bin/python` (system python3 lacks numpy/pandas).
- Commit style: end messages with the Claude Co-Authored-By line. Commit only
  when TJ asks; he usually says "commit and update the scoreboard".
