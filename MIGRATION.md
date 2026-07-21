# Moving this lab to a new Mac (~30 minutes)

1. New Mac: install Homebrew, then: brew install python@3.11 git gh
2. git clone git@github.com:Cryptot86/options-backtest-engine.git Options-Trading
   (set up an SSH key first: gh auth login)
3. Copy from the old Mac (AirDrop, external drive, or: rsync -av over WiFi):
   - data_cache/        (the paid market-data cache — the crown jewels)
   - db/results.sqlite  (every backtest verdict)
   - .env               (the Databento API key — one line)
4. cd Options-Trading && python3 -m venv .venv && source .venv/bin/activate
   && pip install -r requirements.txt
5. Verify: OTBT_OFFLINE=1 python -c "from src.otbt.data import db; print(len(db.list_runs()), 'runs visible')"
   Expect ~100+. Done — every cached dollar of data survives the move.
Memory/Claude files live in ~/.claude/projects/... — Migration Assistant
carries them, or copy that folder too.
