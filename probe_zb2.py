from dotenv import load_dotenv; load_dotenv()
from src.otbt.pricing import glbx_options as gx
import pandas as pd
d = gx.get_option_definitions("ZB", pd.Timestamp("2024-02-01"))
d["dte"] = (d["expiration"].dt.normalize() - pd.Timestamp("2024-02-01")).dt.days
print("expiries and DTEs available:")
print(d.groupby(d["expiration"].dt.date)["dte"].first().to_string())
print("\nraw_symbol samples:", d.raw_symbol.head(3).tolist())
