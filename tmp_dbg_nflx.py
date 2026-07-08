"""Debug NFLX 2022-05-02 ATM selection (uses cached defs; no new pulls)."""
from dotenv import load_dotenv; load_dotenv()
import numpy as np
import pandas as pd
from src.otbt.pricing import databento_options as dbo
from src.otbt.pricing.blackscholes import strike_for_delta

d = pd.Timestamp("2022-05-02")
spot = 199.46
defs = dbo.get_definitions("NFLX", d)
calls = defs[defs["instrument_class"] == "C"].copy()
calls["dte"] = (calls["expiration"] - d).dt.days
calls = calls[(calls["dte"] >= 30) & (calls["dte"] <= 75)]
exp = calls.iloc[(calls["dte"] - 50).abs().argsort().iloc[0]]["dte"]
print("chosen dte:", exp, "expiry:", calls[calls["dte"] == exp]["expiration"].iloc[0])
ce = calls[calls["dte"] == exp].sort_values("strike_price")
ks = ce["strike_price"].values
print("n strikes:", len(ks), "min:", ks.min(), "max:", ks.max())
print("strikes 150-260:", [k for k in ks if 150 <= k <= 260])

# rvol estimate as the runner computes it
CACHE = ("/private/tmp/claude-501/-Users-bhuvitamil-Documents-TJ-Options-Trading/"
         "fc440fb4-da78-4300-83f4-623695102aed/scratchpad/factor_cache")
rc = pd.read_parquet(f"{CACHE}/rawclose_NFLX.parquet")["close"]
lr = np.log(rc).diff()
rv = float((lr.rolling(20).std() * np.sqrt(252)).loc[:d].iloc[-1])
iv_use = max(rv * 1.15, 0.06)
T = int(exp) / 365.0
K = strike_for_delta(spot, T, iv_use, 0.50, kind="call")
print(f"rvol20={rv:.3f} iv_use={iv_use:.3f} T={T:.3f} K_star={K:.1f}")
for ivx in (0.3, 0.6, 1.0, 1.8, 3.0):
    print(f"  iv={ivx}: K_star={strike_for_delta(spot, T, ivx, 0.50, kind='call'):.1f}")
snap = ce.iloc[(ce["strike_price"] - K).abs().argsort().iloc[0]]
print("snapped strike:", snap["strike_price"], snap["raw_symbol"])
