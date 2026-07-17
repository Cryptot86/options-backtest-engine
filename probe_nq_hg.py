from dotenv import load_dotenv; load_dotenv()
from src.otbt.pricing import glbx_options as gx
import pandas as pd
for root in ("NQ","HG"):
    try:
        cont = gx.get_continuous(root, "2024-01-01", "2024-03-01")
        d = gx.get_option_definitions(root, pd.Timestamp("2024-02-01"))
        d["dte"] = (d["expiration"].dt.normalize()-pd.Timestamp("2024-02-01")).dt.days
        n = len(d[(d.dte>=30)&(d.dte<=45)&(d.instrument_class=="P")])
        print(f"{root}: cont {len(cont)} rows, last {float(cont['close'].iloc[-1]):.1f} | defs {len(d)} | 30-45d puts {n}")
    except Exception as e:
        print(f"{root}: PROBE FAILED {type(e).__name__}: {str(e)[:100]}")
