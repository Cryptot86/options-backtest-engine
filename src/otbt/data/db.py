"""SQLite results database.

Backtest results live in a real queryable database (not loose files), per
requirement. One file, no server. Tables:
  runs    - one row per backtest run (id, timestamp, phase, universe, params)
  trades  - every simulated trade, tagged with run_id
  summary - per-strategy metrics for a run, tagged with run_id
"""
from __future__ import annotations

import os
import sqlite3

import pandas as pd

DB_PATH = os.path.join("db", "results.sqlite")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT, phase TEXT, universe TEXT, start TEXT, "end" TEXT,
        n_trades INTEGER, notes TEXT)""")
    return con


def save_run(trades: pd.DataFrame, summary: pd.DataFrame, *, phase: str,
             universe: list[str], start: str, end: str, created_at: str,
             notes: str = "") -> int:
    """Persist a run + its trades + summary. Returns the run_id."""
    con = _conn()
    try:
        cur = con.execute(
            'INSERT INTO runs (created_at, phase, universe, start, "end", n_trades, notes)'
            " VALUES (?,?,?,?,?,?,?)",
            (created_at, phase, ",".join(universe), start, end, len(trades), notes))
        run_id = cur.lastrowid
        t = trades.copy();   t["run_id"] = run_id
        s = summary.copy();  s["run_id"] = run_id
        for c in t.columns:                         # sqlite can't store Timestamps
            if pd.api.types.is_datetime64_any_dtype(t[c]):
                t[c] = t[c].astype(str)
        t.to_sql("trades", con, if_exists="append", index=False)
        s.to_sql("summary", con, if_exists="append", index=False)
        con.commit()
        return run_id
    finally:
        con.close()


def load_latest(phase: str | None = None):
    """Return (run_meta, trades_df, summary_df) for the most recent run."""
    con = _conn()
    try:
        q = "SELECT * FROM runs"
        if phase:
            q += f" WHERE phase = '{phase}'"
        q += " ORDER BY run_id DESC LIMIT 1"
        runs = pd.read_sql(q, con)
        if runs.empty:
            return None, pd.DataFrame(), pd.DataFrame()
        rid = int(runs.iloc[0]["run_id"])
        trades = pd.read_sql(f"SELECT * FROM trades WHERE run_id = {rid}", con)
        summary = pd.read_sql(f"SELECT * FROM summary WHERE run_id = {rid}", con)
        return runs.iloc[0], trades, summary
    finally:
        con.close()


def list_runs() -> pd.DataFrame:
    con = _conn()
    try:
        return pd.read_sql("SELECT * FROM runs ORDER BY run_id DESC", con)
    finally:
        con.close()
