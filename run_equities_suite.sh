#!/bin/sh
# 35-stock equity suite, resume-safe. Checkpoint: output/equities_done.txt
cd "$(dirname "$0")"
. .venv/bin/activate
TICKERS="MSFT NVDA AMZN GOOGL META TSLA AMD NFLX AVGO JPM BAC GS WFC C XOM CVX COP UNH JNJ PFE LLY WMT COST HD MCD NKE BA CAT DE DIS CRM ORCL INTC MU"
for T in $TICKERS; do
  grep -qx "$T" output/equities_done.txt 2>/dev/null && { echo "SKIP $T (done)"; continue; }
  tries=0
  while [ $tries -lt 8 ]; do
    echo ">>> $T (attempt $((tries+1)))"
    python run_backtest_real.py --start 2019-01-01 "$T" > "output/eq_$T.log" 2>&1
    if grep -q "Saved to DB" "output/eq_$T.log"; then
      echo "$T" >> output/equities_done.txt
      echo "DONE $T"; break
    elif grep -qi "insufficient_funds" "output/eq_$T.log"; then
      echo "BUDGET HIT on $T — waiting 10 min for cap raise..."; sleep 600
      tries=$((tries+1))
    else
      echo "FAILED $T (non-budget) — logged, moving on"
      echo "$T FAILED" >> output/equities_failed.txt; break
    fi
  done
done
echo "EQUITIES SUITE COMPLETE ($(wc -l < output/equities_done.txt) done)"
