#!/usr/bin/env python3
"""Pine regression checker — static invariants for pine/tj_scanner.pine.

Pine Script only runs inside TradingView, so this is NOT execution testing.
It is a guard against the SPECIFIC ways we have broken this file before:
  - dropping the D+1 discipline (sigConf must gate on [1], not the live bar)
  - deleting the earnings block, the SIZE row, the gate-at-signal-close display
  - variable typos, unbalanced parens/brackets from a bad edit
Each LAW below maps to a real prior bug or a load-bearing rule. Add a law here
whenever you fix a scanner bug, so it can never silently come back.

Usage:  python3 check_pine.py [file.pine ...]   # one or more files
        python3 check_pine.py --all             # every .pine in the repo
        python3 check_pine.py                    # default: pine/tj_scanner.pine
Exit 0 = all files pass. Exit 1 = any regression in any file. Prints a report.
"""
from __future__ import annotations
import re, sys, os, glob

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def resolve_targets(argv):
    if argv == ["--all"]:
        return sorted(glob.glob(os.path.join(REPO, "**", "*.pine"), recursive=True))
    if argv:
        return argv
    return [os.path.join(REPO, "pine", "tj_scanner.pine")]


def strip_strings_and_comments(src: str) -> str:
    """Remove string literals and // comments so bracket-balance is meaningful.
    Pine strings are double- or single-quoted, no multi-line strings."""
    out = []
    for line in src.splitlines():
        buf = []
        i, n, q = 0, len(line), None
        while i < n:
            c = line[i]
            if q:                      # inside a string
                if c == q:
                    q = None
                i += 1
                continue
            if c in ('"', "'"):
                q = c
                i += 1
                continue
            if c == "/" and i + 1 < n and line[i + 1] == "/":
                break                  # rest of line is a comment
            buf.append(c)
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


# LAWS: (id, human description, regex that MUST be found in the RAW source).
# These are the invariants; each ties to a prior bug or a validated rule.
LAWS = [
    ("version", "Pine v5 header present",
     r"//@version=5"),
    ("indicator", "indicator() declaration present",
     r"indicator\(\s*\"TJ 3-Line Premium Scanner\""),
    # --- D+1 discipline: the bug where we added a live gate check and suppressed valid signals ---
    ("d1-sigconf-trigger", "sigConf uses YESTERDAY's trigger [1] (D+1 discipline)",
     r"sigConf\s*=.*dip2SD\[1\].*low5\[1\]"),
    ("d1-sigconf-gate", "sigConf gates on [1] gate, NOT the live bar (no overcorrection)",
     r"sigConf\s*=.*gateOK\[1\]"),
    ("no-live-gate-in-sigconf", "sigConf must NOT re-check a bare live gateOK (would kill D+1 signals)",
     None),  # special: handled below
    # --- earnings safety (the ACT-NOW-into-earnings bug) ---
    ("earn-block", "sigConf includes noEarnBlock (no selling into earnings)",
     r"sigConf\s*=.*noEarnBlock"),
    # --- trigger definitions must keep the trend filter + prior-bar 5-day low ---
    ("dip-trendup", "2-SD dip trigger requires trendUp",
     r"dip2SD\s*=\s*close\s*<=\s*bbLower\s*and\s*trendUp"),
    ("low5-prior", "5-day-low trigger uses the PRIOR 5-day low [1] (backtest-exact)",
     r"low5\s*=\s*close\s*<=\s*ta\.lowest\(close,\s*5\)\[1\]\s*and\s*trendUp"),
    # --- name-gate only fires when the VIX gate is CLOSED (it is the storm backup) ---
    ("namestorm-not-green", "nameStorm requires 'not gateGreen' (backup only when VIX gate shut)",
     r"nameStorm\s*=.*not\s+gateGreen"),
    # --- the fix we just shipped: name-gate row stands down when VIX gate reopens ---
    ("namegate-standdown", "name-gate row has STAND DOWN branch when mode is off",
     r"STAND DOWN"),
    ("namegate-bg-guard", "name-gate green background requires useNameGate and not gateGreen",
     r"bgcolor=ngStormOK and ngTrigC and isEquity and useNameGate and not gateGreen"),
    # --- gate display must match the decision (the 'at signal close' display fix) ---
    ("gate-at-signal-close", "gate row shows '(at signal close)' when a signal confirmed",
     r"\(at signal close\)"),
    # --- 21-day loss cooldown (LAW 2026-07-30, OOS-validated) ---
    ("cooldown-inputs", "cooldown inputs present (cdRoot + cdLossExit)",
     r"cdRoot\s*=\s*input\.string"),
    ("cooldown-symbol-aware", "cooldown is name-local (matches symbol root only)",
     r"cdMatch\s*=\s*cdRoot\s*!=\s*\"\"\s*and\s*\(syminfo\.root\s*==\s*cdRoot"),
    ("cooldown-action", "ACTION chain has COOLDOWN branch with days-left",
     r"COOLDOWN — \" \+ str\.tostring\(cdDaysLeft\)"),
    ("cooldown-color", "actCol handles cdActive FIRST (no green-bg mismatch)",
     r"actCol\s*=\s*cdActive"),
    ("cooldown-alerts", "sell-put alerts suppressed during cooldown",
     r"sellSignal and dip2SD and not cdActive"),
    # --- straddle light: single stocks need NAME-level cheapness (ARIS fix 2026-08-11) ---
    ("straddle-name-cheap", "straddle light requires the name's OWN vol rank<=30 for stocks",
     r"cheapDay = useStraddle and cheapOK and volRank <= 30 and volIdx < hvRef and nameCheap"),
    # --- straddle whitelist (LAW 2026-08-11, census-confirmed) ---
    ("straddle-whitelist", "straddle gated to ES/CL + 7 mega-caps (stradOK)",
     r"cheapOK\s*=\s*stradOK"),
    ("straddle-nogo-row", "off-whitelist charts show straddle NO-GO",
     r"NO-GO — straddle whitelist"),
    # --- fast-win re-entry hint (2026-08-19): hint only, never a gate ---
    ("fastwin-inputs", "fast-win inputs present (fwRoot + fwExit)",
     r"fwRoot\s*=\s*input\.string"),
    ("fastwin-hint-not-gate", "fast-win is a hint appended to ACTION, cooldown still wins",
     r"fwActive\s*=\s*fwMatch and fwDaysLeft > 0 and not cdActive"),
    # --- SIZE row (2% risk, capped) must stay present ---
    ("size-row", "SIZE row present with 2% risk + anchor + cap",
     r"SIZE \(2% risk"),
    # --- exits law: 50% or 21 DTE, no price stops ---
    ("exit-law", "exit rule row states 50% profit OR 21 DTE, no price stops",
     r"50% profit OR 21 DTE"),
]


def check_file(path: str) -> int:
    path = os.path.normpath(path)
    if not os.path.exists(path):
        print(f"FAIL  cannot find pine file: {path}")
        return 1
    raw = open(path, encoding="utf-8").read()
    stripped = strip_strings_and_comments(raw)

    results = []  # (ok, id, desc, detail)

    # 1) bracket balance on code (strings/comments removed)
    for open_c, close_c, label in [("(", ")", "parens"), ("[", "]", "brackets")]:
        o, c = stripped.count(open_c), stripped.count(close_c)
        results.append((o == c, f"balance-{label}",
                        f"{label} balanced", f"{o} '{open_c}' vs {c} '{close_c}'"))

    # 2) each LAW (per-file set)
    file_laws, check_rows = laws_for(path)
    for lid, desc, pat in file_laws:
        if lid == "no-live-gate-in-sigconf":
            # sigConf line must not contain a bare 'gateOK' without [1]
            m = re.search(r"sigConf\s*=.*", raw)
            line = m.group(0) if m else ""
            bad = re.search(r"gateOK(?!\[1\])", line) is not None
            results.append((not bad, lid, desc,
                            "found bare live gateOK in sigConf" if bad else "clean"))
            continue
        found = re.search(pat, raw, re.DOTALL) is not None
        results.append((found, lid, desc, "found" if found else "MISSING pattern"))

    # 3) table.cell row-index coverage (scanner only)
    if not check_rows:
        rows_ok = True
    rows = sorted(set(int(m) for m in re.findall(r"table\.cell\(tb,\s*\d+,\s*(\d+)", raw)))
    expected = list(range(0, 15))
    missing_rows = [] if not check_rows else [r for r in expected if r not in rows]
    results.append((not missing_rows, "table-rows",
                    "table rows 0..14 all populated",
                    "ok" if not missing_rows else f"missing rows {missing_rows}"))

    # report
    width = max(len(r[1]) for r in results)
    fails = 0
    print(f"\nPine regression — {os.path.basename(path)}\n" + "-" * 60)
    for ok, lid, desc, detail in results:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{tag}] {lid:<{width}}  {desc}" + ("" if ok else f"  <-- {detail}"))
    print("-" * 60)
    print(f"{len(results)-fails}/{len(results)} passed"
          + ("" if not fails else f"  — {fails} REGRESSION(S)"))
    return 1 if fails else 0


BBMR_LAWS = [
    ("version", "Pine v5 header present", r"//@version=5"),
    ("indicator", "indicator() declaration present", r"indicator\(\s*\"TJ BB-MR Stocks"),
    ("candidate-banner", "CANDIDATE (not law) status visible in table", r"CANDIDATE — not law"),
    ("no-repaint", "entry/exit act on confirmed bars only", r"barstate\.isconfirmed"),
    ("young-ipo-warning", "young-IPO (ARM/RDDT) negative warning present", r"ARM/RDDT"),
    ("costs-input", "round-trip cost input present", r"costBps\s*=\s*input"),
    ("entry-def", "entry = close below lower band", r"close < lower"),
    ("exit-def", "exit = close at/above basis", r"close >= basis"),
]


def laws_for(path: str):
    b = os.path.basename(path)
    if "tj_scanner" in b:
        return LAWS, True          # (laws, check table rows 0..14)
    if "bbmr" in b:
        return BBMR_LAWS, False
    return [("version", "Pine v5 header present", r"//@version=5")], False


def main() -> int:
    targets = resolve_targets(sys.argv[1:])
    if not targets:
        print("no .pine files found")
        return 1
    rc = 0
    for t in targets:
        rc |= check_file(t)
    if len(targets) > 1:
        print(f"\n==== {len(targets)} file(s) checked — "
              + ("ALL GREEN" if rc == 0 else "REGRESSION(S) PRESENT") + " ====")
    return rc


if __name__ == "__main__":
    sys.exit(main())
