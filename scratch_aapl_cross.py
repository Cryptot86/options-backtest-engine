from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.data.prices import get_prices
from src.otbt.signals.engine import _prep
from src.otbt.pricing.simulate_real import simulate_real_trade

px = _prep(get_prices("AAPL", "2018-06-01", "2025-06-30"))
up = px["trend_up"]; idx = px.index
bull = up & ~up.shift(1, fill_value=False)
entries = []
for d in idx[bull]:
    pos = idx.searchsorted(d) + 1          # D+1, your workflow
    if pos < len(idx) and idx[pos] >= pd.Timestamp("2019-01-01"):
        entries.append(idx[pos])
print(f"AAPL bullish 10x100 crosses 2019-2025: {len(entries)}")
rows = []
for d in entries:
    iv = float(px.loc[d, "rvol20"]) if pd.notna(px.loc[d, "rvol20"]) else 0.3
    try:
        r = simulate_real_trade("AAPL", d, px, "cross_put", iv)
    except Exception as e:
        r = None; print(d.date(), "err", str(e)[:60])
    if r: rows.append(r.__dict__)
t = pd.DataFrame(rows)
if len(t):
    pd.set_option("display.width", 200)
    print(t[["entry_date","exit_date","strike","entry_credit","pnl","exit_reason","days_held","mae"]].to_string(index=False))
    print(f"\nn={len(t)} | win% {100*(t.pnl>0).mean():.0f} | expectancy ${t.pnl.mean():.0f} "
          f"| total ${t.pnl.sum():.0f} | worst ${t.pnl.min():.0f}")
