from dotenv import load_dotenv; load_dotenv()
from src.otbt.pricing import glbx_options as gx
import pandas as pd
cont = gx.get_continuous("RTY", "2024-01-01", "2024-03-01")
print("RTY continuous rows:", len(cont), "| last close:", float(cont["close"].iloc[-1]))
d = gx.get_option_definitions("RTY", pd.Timestamp("2024-02-01"))
print("RTO+RTM definitions:", len(d))
if len(d):
    d["dte"] = (d["expiration"].dt.normalize() - pd.Timestamp("2024-02-01")).dt.days
    sub = d[(d.dte>=30)&(d.dte<=45)&(d.instrument_class=="P")]
    print("30-45 DTE puts:", len(sub))
    print("expiry DTEs:", sorted(d[d.dte.between(0,90)]["dte"].unique())[:12])
