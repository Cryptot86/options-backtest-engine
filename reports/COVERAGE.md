# Coverage Audit — every tested strategy family

*Generated 2026-07-05. Signals regenerated independently and joined against DB trades.*

| family                   |   run |   signals |   priced |   coverage |
|:-------------------------|------:|----------:|---------:|-----------:|
| ES puts (same-day)       |    25 |       865 |      799 |       92.4 |
| GC puts (same-day)       |    14 |       611 |      564 |       92.3 |
| CL puts (same-day)       |     9 |       560 |      517 |       92.3 |
| NG puts (same-day)       |     8 |       473 |      398 |       84.1 |
| 6B puts (same-day)       |    17 |       619 |      334 |       54   |
| 6E puts (same-day)       |    16 |       545 |      291 |       53.4 |
| CL puts (D+1)            |    19 |       559 |      465 |       83.2 |
| NG puts (D+1)            |    20 |       473 |      376 |       79.5 |
| ES puts (D+1)            |    66 |       865 |      703 |       81.3 |
| GC puts (D+1)            |    30 |       610 |      490 |       80.3 |
| NG calls (same-day)      |    21 |       461 |      385 |       83.5 |
| NG calls (D+1)           |    27 |       461 |      383 |       83.1 |
| CL calls (same-day)      |    22 |       413 |      377 |       91.3 |
| CL calls (D+1)           |    28 |       413 |      342 |       82.8 |
| 10x100 crosses (all fut) |    67 |       480 |      340 |       70.8 |
| MSFT puts (same-day)     |    34 |       225 |      224 |       99.6 |
| AAPL puts (same-day)     |    32 |       251 |      240 |       95.6 |

## Miss reasons
- **ES puts (same-day)** (run 25): {'price_missing_or_error': 66}
- **GC puts (same-day)** (run 14): {'price_missing_or_error': 47}
- **CL puts (same-day)** (run 9): {'price_missing_or_error': 43}
- **NG puts (same-day)** (run 8): {'price_missing_or_error': 75}
- **6B puts (same-day)** (run 17): {'no_definitions': 203, 'no_expiry_in_window': 4, 'price_missing_or_error': 78}
- **6E puts (same-day)** (run 16): {'no_definitions': 211, 'no_expiry_in_window': 22, 'price_missing_or_error': 21}
- **CL puts (D+1)** (run 19): {'price_missing_or_error': 94}
- **NG puts (D+1)** (run 20): {'price_missing_or_error': 96, 'no_definitions': 1}
- **ES puts (D+1)** (run 66): {'price_missing_or_error': 162}
- **GC puts (D+1)** (run 30): {'price_missing_or_error': 114, 'no_definitions': 6}
- **NG calls (same-day)** (run 21): {'price_missing_or_error': 72, 'no_definitions': 4}
- **NG calls (D+1)** (run 27): {'price_missing_or_error': 78}
- **CL calls (same-day)** (run 22): {'price_missing_or_error': 36}
- **CL calls (D+1)** (run 28): {'price_missing_or_error': 71}
- **10x100 crosses (all fut)** (run 67): {'price_missing_or_error': 81, 'no_definitions': 52, 'no_expiry_in_window': 7}
- **MSFT puts (same-day)** (run 34): {'equity_unpriced': 1}
- **AAPL puts (same-day)** (run 32): {'equity_unpriced': 11}

**TOTAL: 7228/8884 = 81.4% coverage**
