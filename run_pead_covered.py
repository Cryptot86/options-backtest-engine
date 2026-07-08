"""PEAD covered variant (book): beat -> long 100sh + sell ~30d call;
miss -> short 100sh + sell ~30d put. D+1, ~25DTE, hold to expiry."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd, yfinance as yf
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def covered(sym, e, px, beat):
    spot = float(px.loc[e,"close"]); iv = 0.35
    kind = "call" if beat else "put"
    O = dbo.select_16d_modeled(sym, e, spot, iv, dte_min=15, dte_max=40, dte_target=25,
                               target_delta=0.30, kind=kind)
    if O is None: return None
    m = getattr(O, "scale", 1.0)
    op = dbo.get_symbol_daily(O.raw_symbol, e, pd.Timestamp(O.expiration)).set_index("date")["mid"] / m
    if e not in op.index: return None
    prem = float(op.loc[e])
    expd = pd.Timestamp(O.expiration)
    fwd = px.loc[e:expd]; F = float(fwd["close"].iloc[-1])
    K = O.strike/m
    if beat:   # long shares + short call
        pnl = (min(F, K) - spot)*100 + prem*100
    else:      # short shares + short put
        pnl = (spot - max(F, K))*100 + prem*100
    return dict(symbol=sym, entry_date=e, exit_date=fwd.index[-1], strike=K,
                dte=int((expd-e).days), entry_iv=float("nan"), entry_delta=0.30,
                entry_credit=prem*100, pnl=pnl-2.0, pnl_pct_credit=pnl/(prem*100) if prem>0 else 0,
                mae=float("nan"), days_held=int((fwd.index[-1]-e).days),
                exit_reason="expiry", signal_type="pead_cov_"+("beat" if beat else "miss"))

rows=[]
for sym in ("AAPL","MSFT","NVDA","META","GOOGL"):
    ed = yf.Ticker(sym).get_earnings_dates(limit=60)
    ed = ed.dropna(subset=["Reported EPS","EPS Estimate"])
    ed.index = pd.to_datetime(ed.index).tz_localize(None).normalize()
    ed = ed[(ed.index>="2019-06-01")&(ed.index<="2026-06-01")]
    ed["beat"] = ed["Reported EPS"] > ed["EPS Estimate"]
    px = get_prices(sym,"2019-01-01","2026-06-30"); idx = px.index
    for dt,r in ed.sort_index().iterrows():
        pos = idx.searchsorted(dt)+1
        if pos>=len(idx): continue
        for att in range(20):
            try:
                tr = covered(sym, idx[pos], px, bool(r.beat))
                if tr: rows.append(tr)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                else: print(f"ERR {sym} {idx[pos].date()}: {ex}", flush=True); break
    done=[x for x in rows if x["symbol"]==sym]
    if done:
        t=pd.DataFrame(done)
        print(f"-> {sym}: n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} tot=${t.pnl.sum():,.0f}", flush=True)
if rows:
    t=pd.DataFrame(rows)
    print("\n=== covered PEAD pooled ===")
    print(t.groupby("signal_type")["pnl"].agg(["size","mean","sum"]).round(0).to_string())
    db.save_run(t, summarize(t), phase="pead_covered", universe=sorted(t.symbol.unique()),
                start="2019-06-01", end="2026-06-01",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="PEAD covered: beat=shares+30d call; miss=short+30d put; D+1 ~25DTE to expiry")
print("PEAD COVERED DONE")
