from dotenv import load_dotenv; load_dotenv()
import databento as dbn, os
c = dbn.Historical(os.environ["DATABENTO_API_KEY"])
for root in ("HXE","HG","HGO","CU","HX1"):
    try:
        r = c.symbology.resolve(dataset="GLBX.MDP3", symbols=[f"{root}.OPT"],
            stype_in="parent", stype_out="instrument_id", start_date="2024-02-01", end_date="2024-02-02")
        n = sum(len(v) for v in r["result"].values()) if isinstance(r, dict) and "result" in r else "?"
        print(f"{root}.OPT -> resolved ({n} ids)")
    except Exception as e:
        print(f"{root}.OPT -> {str(e)[:60]}")
