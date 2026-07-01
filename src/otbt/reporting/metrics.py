"""Layer 3 — per-hypothesis metrics.

Reports exactly the fields the charter requires: n, win %, expectancy,
avg win, avg loss, avg-win/avg-loss ratio, MAE distribution, worst loss,
signal frequency per month, and the delta vs the H6 baseline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def results_frame(results: list) -> pd.DataFrame:
    """Turn a list of TradeResult dataclasses into a tidy DataFrame."""
    return pd.DataFrame([r.__dict__ for r in results if r is not None])


def _span_months(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    d = pd.to_datetime(df["entry_date"])
    return max((d.max() - d.min()).days / 30.44, 1.0)


def summarize(df: pd.DataFrame, baseline_expectancy: float | None = None) -> pd.DataFrame:
    """One row per signal_type with the charter metric set."""
    if df.empty:
        return pd.DataFrame()
    out = []
    for sig, g in df.groupby("signal_type"):
        wins = g[g["pnl"] > 0]["pnl"]
        losses = g[g["pnl"] <= 0]["pnl"]
        avg_win = wins.mean() if len(wins) else 0.0
        avg_loss = losses.mean() if len(losses) else 0.0
        expectancy = g["pnl"].mean()
        row = {
            "signal_type": sig,
            "n": len(g),
            "per_month": round(len(g) / _span_months(g), 2),
            "win_pct": round(100 * (g["pnl"] > 0).mean(), 1),
            "expectancy": round(expectancy, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss else np.nan,
            "worst_loss": round(g["pnl"].min(), 2),
            "mae_p50": round(g["mae"].median(), 2),
            "mae_p95": round(g["mae"].quantile(0.05), 2),   # 5th pctile = deep adverse
            "avg_days": round(g["days_held"].mean(), 1),
        }
        if baseline_expectancy is not None:
            row["delta_vs_baseline"] = round(expectancy - baseline_expectancy, 2)
        out.append(row)
    res = pd.DataFrame(out).sort_values("expectancy", ascending=False)
    return res.reset_index(drop=True)
