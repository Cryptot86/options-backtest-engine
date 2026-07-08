from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
cont = gx.get_continuous("ES", "2025-09-01", "2026-07-08")
pp = _prep(cont)
pp["fdl"] = (pp["close"] <= pp["close"].rolling(5).min().shift(1)) & pp["trend_up"]
pp["bb"]  = (pp["close"] <= pp["bb_lower"]) & pp["trend_up"]
t = pp.tail(6)[["close","ema10","ema100","trend_up","bb","fdl"]]
print(t.round(1).to_string())
last = pp.iloc[-1]
print(f"\nlatest bar {pp.index[-1].date()}: trend_up={bool(last.trend_up)} five_day_low={bool(last.fdl)} bb_2sd={bool(last.bb)}")
prev = pp.iloc[-2]
print(f"prior bar  {pp.index[-2].date()}: five_day_low={bool(prev.fdl)} bb_2sd={bool(prev.bb)}")
