"""N-day-low robustness: N in 3..7 on ES, D+1, same management. $0 GLBX."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
root = "ES"
cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
pp = _prep(cont); idx = pp.index
print("N-day-low sensitivity on ES (D+1, 16d put, 50%/21DTE):", flush=True)
for N in (3, 4, 5, 6, 7):
    hit = (pp["close"] <= pp["close"].rolling(N).min()) & pp["trend_up"]
    entry = hit & ~hit.shift(1, fill_value=False)
    days = []
    for d in idx[entry]:
        pos = idx.searchsorted(d) + 1
        if pos < len(idx) and pd.notna(pp.loc[d, "rvol20"]):
            days.append((idx[pos], float(pp.loc[d, "rvol20"])))
    res = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(gx.simulate_fut_trade, root, e, pp, f"{N}dl", iv) for e, iv in days]
        for f in as_completed(futs):
            try: r = f.result()
            except Exception: r = None
            if r: res.append(r.pnl)
    s = pd.Series(res)
    print(f"  N={N}: n={len(s):3d}  $/trade={s.mean():7,.0f}  win%={100*(s>0).mean():4.1f}  "
          f"worst={s.min():9,.0f}  total={s.sum():10,.0f}", flush=True)
print("NDAY SENSITIVITY DONE")
