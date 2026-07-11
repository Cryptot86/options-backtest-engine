# Worst-loss reference table (from 13-yr backtest DB, generated 2026-07-11)

Feeds the UNDEFINED-risk sizing formula:
  contracts = floor(2% * equity / |historical worst loss per contract|)
`p95_loss` = 95th-percentile loss (the "ordinary bad day"); `worst` = the
13-year record (the sizing anchor). All $ per contract, net of costs.

| line                    | n     | worst    | p95 loss | avg P&L | 2% sizing on $50K       |
|-------------------------|-------|----------|----------|---------|--------------------------|
| SHORT_PUT ES (full)     | 439   | -15,689  | -1,266   | +396    | 0 (too big — use MES)    |
| SHORT_PUT MES (micro)   | 439   | -1,569   | -127     | +40     | max(1, floor(1000/1569)) = **1** |
| SHORT_PUT GC            | 277   | -8,232   | -1,150   | +143    | 0 full / consider MGC    |
| SHORT_CALL NG           | 48    | -451     | -204     | +304    | **2** contracts          |
| SHORT_CALL CL           | 32    | -2,902   | -1,114   | +126    | 0 full / MCL if listed   |
| SHORT_CALL ZB (candidate)| 33   | -673     | -251     | +152    | **1** (paper only)       |
| SHORT_PUT stocks (class, UNGATED stats) | 1,805 | -17,986* | -462 | +8 | *gate+name-IV+dedupe cut this tail to ~-4,520 observed; size 1 contract/name, basket-diversified |
| LONG_STRADDLE (defined — reference) | 217 | -6,522 (full ES) | -2,562 | +89 | sized by debit<=2%, not this table |
| LONG_CALL micro ES/GC (defined) | 65 | -373 | -307 | +86 | sized by debit |

*Stock caveat: the ungated class worst (-$17,986) is the pre-filter world;
the deployed line (gate + name-IV>=35 + dedupe + basket) observed worst
-$4,520. Engine should use -4,520 as the stock sizing anchor and revisit as
live data accumulates.
