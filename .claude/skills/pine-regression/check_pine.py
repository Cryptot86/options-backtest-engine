#!/usr/bin/env python3
"""Pine regression checker — static invariants for pine/tj_scanner.pine.

Pine Script only runs inside TradingView, so this is NOT execution testing.
It is a guard against the SPECIFIC ways we have broken this file before:
  - dropping the D+1 discipline (sigConf must gate on [1], not the live bar)
  - deleting the earnings block, the SIZE row, the gate-at-signal-close display
  - variable typos, unbalanced parens/brackets from a bad edit
Each LAW below maps to a real prior bug or a load-bearing rule. Add a law here
whenever you fix a scanner bug, so it can never silently come back.

Usage:  python3 check_pine.py [path/to/tj_scanner.pine]
Exit 0 = all pass. Exit 1 = at least one regression. Prints a report.
"""
from __future__ import annotations
import re, sys, os

PINE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "pine", "tj_scanner.pine")


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
    # --- SIZE row (2% risk, capped) must stay present ---
    ("size-row", "SIZE row present with 2% risk + anchor + cap",
     r"SIZE \(2% risk"),
    # --- exits law: 50% or 21 DTE, no price stops ---
    ("exit-law", "exit rule row states 50% profit OR 21 DTE, no price stops",
     r"50% profit OR 21 DTE"),
]


def main() -> int:
    path = os.path.normpath(PINE)
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

    # 2) each LAW
    for lid, desc, pat in LAWS:
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

    # 3) table.cell row-index coverage: rows 0..14 should all appear (15-row table)
    rows = sorted(set(int(m) for m in re.findall(r"table\.cell\(tb,\s*\d+,\s*(\d+)", raw)))
    expected = list(range(0, 15))
    missing_rows = [r for r in expected if r not in rows]
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


if __name__ == "__main__":
    sys.exit(main())
