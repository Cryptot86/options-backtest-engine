from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

all_rows = []
for root in ["ES", "GC", "CL", "NG", "6B", "6E"]:
    cont = gx.get_continuous(root, "2012-01-01", "2025-06-30")
    if cont.empty:
        continue
    pp = _prep(cont)
    up = pp["trend_up"]
    bull = up & ~up.shift(1, fill_value=False)
    bear = ~up & up.shift(1, fill_value=True)
    idx = pp.index
    jobs = []
    for d in idx[bull]:
        pos = idx.searchsorted(d) + 1
        if pos < len(idx):
            jobs.append((idx[pos], "put"))
    for d in idx[bear]:
        pos = idx.searchsorted(d) + 1
        if pos < len(idx):
            jobs.append((idx[pos], "call"))
    print(f"{root}: {sum(1 for _,k in jobs if k=='put')} bull / "
          f"{sum(1 for _,k in jobs if k=='call')} bear crosses", flush=True)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(gx.simulate_fut_trade, root, d, pp, f"cross_{k}",
                          float(pp.loc[d, 'rvol20']) if pd.notna(pp.loc[d, 'rvol20']) else 0.3,
                          kind=k) for d, k in jobs]
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                all_rows.append(r)

rdf = pd.DataFrame([r.__dict__ for r in all_rows])
print(f"\npriced: {len(rdf)}")
pd.set_option("display.width", 200)
g = rdf.groupby(["symbol", "signal_type"])["pnl"].agg(["size", "mean", "min"]).round(0)
g.columns = ["n", "expectancy", "worst"]
print("\n=== per market x side ===")
print(g.to_string())
print("\n=== pooled ===")
s = summarize(rdf)
print(s.to_string(index=False))
rid = db.save_run(rdf, s, phase="cross_entry", universe=["multi"],
                  start="2012-01-01", end="2025-06-30",
                  created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  notes="fresh 10x100 cross entries, D+1: bull->put, bear->call")
print(f"saved run_id={rid}")
print("CROSS TEST DONE")
