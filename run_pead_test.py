"""PEAD (book): after earnings BEAT -> long 40/10 call spread ~30DTE;
after MISS -> long 50/20 put spread. D+1 entry, hold to expiry. Real OPRA."""
from dotenv import load_dotenv; load_dotenv()
import time as _t
import pandas as pd, yfinance as yf
from datetime import datetime, timezone
from src.otbt.data.prices import get_prices
from src.otbt.pricing import databento_options as dbo
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db

def spread(sym, e, px, kind, d_long, d_short):
    spot = float(px.loc[e, "close"]); iv = 0.35
    L = dbo.select_16d_modeled(sym, e, spot, iv, dte_min=15, dte_max=40, dte_target=25,
                               target_delta=d_long, kind=kind)
    S = dbo.select_16d_modeled(sym, e, spot, iv, dte_min=15, dte_max=40, dte_target=25,
                               target_delta=d_short, kind=kind)
    if L is None or S is None or L.expiration != S.expiration or L.strike == S.strike: return None
    m = getattr(L, "scale", 1.0)
    lp = dbo.get_symbol_daily(L.raw_symbol, e, pd.Timestamp(L.expiration)).set_index("date")["mid"] / m
    sp = dbo.get_symbol_daily(S.raw_symbol, e, pd.Timestamp(S.expiration)).set_index("date")["mid"] / m
    if e not in lp.index or e not in sp.index: return None
    d0 = float(lp.loc[e]) - float(sp.loc[e])
    if d0 <= 0: return None
    expd = pd.Timestamp(L.expiration)
    fwd = px.loc[e:expd]
    F = float(fwd["close"].iloc[-1])
    KL, KS = L.strike/m, S.strike/m
    if kind == "call": xv = max(F-KL,0.0) - max(F-KS,0.0)
    else:              xv = max(KL-F,0.0) - max(KS-F,0.0)
    return dict(symbol=sym, entry_date=e, exit_date=fwd.index[-1], strike=KL,
                dte=int((expd-e).days), entry_iv=float("nan"), entry_delta=d_long,
                entry_credit=-d0*100, pnl=(xv-d0)*100 - 4.0,
                pnl_pct_credit=(xv-d0)/d0, mae=float("nan"),
                days_held=int((fwd.index[-1]-e).days), exit_reason="expiry")

rows=[]
for sym in ("AAPL","MSFT","NVDA","META","GOOGL"):
    tk = yf.Ticker(sym)
    ed = tk.get_earnings_dates(limit=60)
    ed = ed.dropna(subset=["Reported EPS","EPS Estimate"])
    ed.index = pd.to_datetime(ed.index).tz_localize(None).normalize()
    ed = ed[(ed.index >= "2019-06-01") & (ed.index <= "2026-06-01")]
    ed["beat"] = ed["Reported EPS"] > ed["EPS Estimate"]
    ed["surp"] = (ed["Reported EPS"]-ed["EPS Estimate"])/ed["EPS Estimate"].abs()*100
    px = get_prices(sym, "2019-01-01", "2026-06-30")
    idx = px.index
    print(f"{sym}: {len(ed)} earnings | beats {int(ed.beat.sum())} misses {int((~ed.beat).sum())}", flush=True)
    for dt, r in ed.sort_index().iterrows():
        pos = idx.searchsorted(dt) + 1          # D+1 after announcement date
        if pos >= len(idx): continue
        e = idx[pos]
        kind, dl, ds = ("call",0.40,0.10) if r.beat else ("put",0.50,0.20)
        for att in range(20):
            try:
                tr = spread(sym, e, px, kind, dl, ds)
                if tr:
                    tr["signal_type"] = ("pead_beat" if r.beat else "pead_miss") + ("_big" if abs(r.surp)>=5 else "")
                    rows.append(tr)
                break
            except Exception as ex:
                if "insufficient" in str(ex).lower(): print("BUDGET WAIT", flush=True); _t.sleep(300)
                else:
                    print(f"ERR {sym} {e.date()}: {type(ex).__name__}: {ex}", flush=True)
                    break
    done = [x for x in rows if x["symbol"]==sym]
    if done:
        t=pd.DataFrame(done)
        print(f"  -> {sym}: n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} tot=${t.pnl.sum():,.0f}", flush=True)
if rows:
    t=pd.DataFrame(rows)
    print("\n=== PEAD pooled ===")
    print(t.groupby(t.signal_type.str.replace('_big',''))["pnl"].agg(["size","mean","sum"]).round(0).to_string())
    big = t[t.signal_type.str.endswith("_big")]
    print(f"big surprises (|surp|>=5%): n={len(big)} $/tr=${big.pnl.mean():,.0f} tot=${big.pnl.sum():,.0f}")
    db.save_run(t, summarize(t), phase="pead_book", universe=sorted(t.symbol.unique()),
                start="2019-06-01", end="2026-06-01",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="PEAD: beat->40/10 call spread, miss->50/20 put spread, D+1, ~30DTE to expiry")
print("PEAD TEST DONE")
