"""Profit-target sweep on ES playbook entries. Judged on TOYOTA metrics:
win%, tail (worst + MAE p95), days-in-market — not just $/trade."""
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.otbt.config import TradeConfig
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import generate_signals, _prep

root = "ES"
cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
pp = _prep(cont); idx = pp.index
led = generate_signals({root: cont})
led = led[led["signal_type"].isin(["five_day_low","bb_2sd"]) & led["iv_proxy"].notna()]
entries = []
for _, s in led.iterrows():
    pos = idx.searchsorted(pd.Timestamp(s["date"])) + 1     # D+1
    if pos < len(idx):
        entries.append((idx[pos], float(s["iv_proxy"])))
print(f"{len(entries)} ES entries; sweeping profit target:", flush=True)
print(f"{'TP':>5} {'n':>4} {'$/trade':>8} {'win%':>6} {'worst':>9} {'maeP95':>9} {'avg days':>9}")
for tp in (0.25, 0.40, 0.50, 0.60, 0.75):
    tc = TradeConfig(take_profit_pct=tp)
    res = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(gx.simulate_fut_trade, root, e, pp, "tp", iv, trade=tc)
                for e, iv in entries]
        for f in as_completed(futs):
            try: r = f.result()
            except Exception: r = None
            if r: res.append((r.pnl, r.mae, r.days_held))
    d = pd.DataFrame(res, columns=["pnl","mae","days"])
    print(f"{int(tp*100):>4}% {len(d):>4} {d.pnl.mean():>8,.0f} {100*(d.pnl>0).mean():>5.1f}% "
          f"{d.pnl.min():>9,.0f} {d.mae.quantile(.05):>9,.0f} {d.days.mean():>8.1f}", flush=True)
print("TP SWEEP DONE")
