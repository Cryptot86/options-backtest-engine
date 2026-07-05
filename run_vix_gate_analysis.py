"""Capstone: VIX 3-dial gate over ALL equity trades (31 names). $0 offline."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd, numpy as np
from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.signals.indicators import realized_vol

# VIX dials (free): rank vs trailing year, spread vs SPY 20d RV, 5-day slope
vix = get_prices("^VIX", "2017-01-01", "2025-06-30")["close"]
spy = get_prices("SPY", "2017-01-01", "2025-06-30")["close"]
rank = vix.rolling(252).apply(lambda w: (w.iloc[-1] >= w).mean())
rv = realized_vol(spy, 20) * 100
spread = vix - rv.reindex(vix.index)
slope5 = vix.diff(5)
gate = (rank >= 0.5) & (spread > 0) & (slope5 <= 0)
dials = pd.DataFrame({"gate": gate, "vix": vix, "rank": rank})

runs = db.list_runs()
eq = runs[(runs["phase"] == "phase1_realiv") & (runs["run_id"] >= 32)]["run_id"].tolist()
t = pd.read_sql(f'SELECT symbol, signal_type, entry_date, pnl, mae FROM trades '
                f'WHERE run_id IN ({",".join(map(str, eq))})', db._conn())
t["entry_date"] = pd.to_datetime(t["entry_date"])
t = t.join(dials, on="entry_date", how="inner")
print(f"{t.symbol.nunique()} names, {len(t)} trades with VIX dials\n")
pd.set_option("display.width", 220)

print("=== VIX 3-GREEN GATE: gated vs ungated, per method ===")
g = t.groupby(["signal_type", "gate"])["pnl"].agg(["size", "mean", "min"]).round(0)
g.columns = ["n", "expectancy", "worst"]
print(g.to_string())

print("\n=== gate verdict pooled (all methods) ===")
p = t.groupby("gate").agg(n=("pnl", "size"), exp=("pnl", "mean"),
                          worst=("pnl", "min"), mae_p95=("mae", lambda x: x.quantile(.05)),
                          total=("pnl", "sum")).round(0)
print(p.to_string())

print("\n=== by VIX rank quartile (pooled) ===")
t["rq"] = pd.cut(t["rank"], [0, .25, .5, .75, 1.0])
q = t.groupby("rq", observed=True)["pnl"].agg(["size", "mean", "min"]).round(0)
print(q.to_string())
print("\nVIX GATE ANALYSIS DONE")
