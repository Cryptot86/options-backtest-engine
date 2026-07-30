---
name: pine-regression
description: Regression-test pine/tj_scanner.pine after any edit. Runs static-invariant checks that guard the load-bearing scanner laws (D+1 gate discipline, earnings block, name-gate stand-down, SIZE row, bracket balance) so a change can't silently reintroduce a past bug. Invoke before committing any change to the pine scanner.
---

# Pine regression test

Pine Script only executes inside TradingView, so this is **not** runtime testing.
It is a static guard against the specific ways `pine/tj_scanner.pine` has been
broken before — each check maps to a real prior bug or a validated rule.

## When to run
- After ANY edit to `pine/tj_scanner.pine`, before committing.
- Whenever TJ reports a scanner contradiction (ACT-NOW vs gate mismatch, missing
  signal, wrong row) — run first to see if a law was violated.

## How to run
```bash
python3 .claude/skills/pine-regression/check_pine.py --all   # every .pine in the repo
python3 .claude/skills/pine-regression/check_pine.py pine/tj_scanner.pine   # one file
```
Exit 0 = all invariants hold. Exit 1 = at least one regression (the report names
which law and why). Do not commit a pine change while this exits non-zero.

## What it checks (the laws)
Structural: bracket/paren balance (strings + comments stripped), Pine v5 header,
`indicator()` present, table rows 0..14 all populated.

Encoded laws (each tied to a bug we already fixed — see comments in the script):
- **D+1 discipline** — `sigConf` gates on yesterday's `[1]` trigger AND `[1]`
  gate, never a bare live `gateOK`. (The overcorrection that suppressed valid
  D+1 signals.)
- **Earnings block** — `sigConf` includes `noEarnBlock`. (The ACT-NOW-into-
  earnings bug.)
- **Trigger defs** — 2-SD dip requires `trendUp`; 5-day-low uses the PRIOR bar
  `ta.lowest(close,5)[1]` (backtest-exact).
- **Name-gate is a backup** — `nameStorm` requires `not gateGreen` (fires only
  when the VIX gate is shut).
- **Name-gate stand-down** — the name-gate row shows STAND DOWN and drops its
  green background when the VIX gate reopens (`useNameGate and not gateGreen`).
  (The all-green-READY-but-ACTION-NOTHING mismatch.)
- **Gate display** — gate row shows `(at signal close)` so it matches the
  decision, not the live tick.
- **SIZE row** present (2% risk, anchor, cap). **Exit law** row = 50% or 21 DTE.

## Extending it (do this every time you fix a scanner bug)
Open `check_pine.py`, add a tuple to the `LAWS` list:
`("my-law-id", "human description of the rule", r"regex that MUST be present")`.
Use `None` as the pattern and add a special-case branch in `main()` for a
"must NOT be present" law (see `no-live-gate-in-sigconf`). Then re-run to confirm
the new law passes on the current (correct) file, and — the important half —
temporarily break the file to confirm the check FAILS. A regression test that
can't fail is theater; prove it bites before you trust it.
