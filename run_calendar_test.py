"""H14: ATM put CALENDAR (sell ~30DTE / buy ~90DTE, same strike) when vol cheap.
Arms: (a) dial-cheap (rank<=0.3 & IV<RV), (b) TJ spec VIX<15 (ES only).
Exits: +40% debit / -50% / front 7DTE. ES/CL/GC(control). $0 GLBX."""
from dotenv import load_dotenv; load_dotenv()
import os, pandas as pd
from datetime import datetime, timezone
from src.otbt.pricing import glbx_options as gx
from src.otbt.signals.engine import _prep
from src.otbt.reporting.metrics import summarize
from src.otbt.data import db
from src.otbt.data.prices import get_prices

def calendar(root, e, pp):
    mult = gx.FUT_SPECS[root]["mult"]
    defs = gx.get_option_definitions(root, e)
    if defs.empty: return None
    o = defs[defs["instrument_class"]=="P"].copy()
    o["dte"] = (o["expiration"].dt.normalize()-e).dt.days
    F = float(pp.loc[e,"close"])
    fr = o[(o.dte>=25)&(o.dte<=45)]
    bk = o[(o.dte>=75)&(o.dte<=120)]
    if fr.empty or bk.empty: return None
    fdte = fr.iloc[(fr.dte-30).abs().argsort().iloc[0]].dte; fr = fr[fr.dte==fdte]
    K = float(fr.iloc[(fr.strike_price-F).abs().argsort().iloc[0]].strike_price)
    frow = fr[fr.strike_price==K].iloc[0]
    bk2 = bk[bk.strike_price==K]
    if bk2.empty: return None
    bdte = bk2.iloc[(bk2.dte-90).abs().argsort().iloc[0]].dte
    brow = bk2[bk2.dte==bdte].iloc[0]
    fp = gx.get_option_path(str(frow.raw_symbol), e, pd.Timestamp(frow.expiration).normalize())
    bp = gx.get_option_path(str(brow.raw_symbol), e, pd.Timestamp(frow.expiration).normalize())
    if fp.empty or bp.empty: return None
    fp = fp.set_index("date")["mid"]; bp = bp.set_index("date")["mid"]
    if e not in fp.index or e not in bp.index: return None
    d0 = float(bp.loc[e]) - float(fp.loc[e])           # net debit (long calendar)
    if d0 <= 0: return None
    lf, lb, worst = float(fp.loc[e]), float(bp.loc[e]), 0.0
    fexp = pd.Timestamp(frow.expiration).normalize()
    days = pp.loc[e:fexp].index
    reason, xd, xv = "front_expiry", days[-1], None
    for dt in days[1:]:
        if dt in fp.index: lf = float(fp.loc[dt])
        if dt in bp.index: lb = float(bp.loc[dt])
        v = lb - lf
        worst = min(worst, (v-d0)*mult)
        dte = (fexp - dt).days
        if v >= 1.4*d0: reason, xd, xv = "tp_40", dt, v; break
        if v <= 0.5*d0: reason, xd, xv = "sl_50", dt, v; break
        if dte <= 7:    reason, xd, xv = "front_7dte", dt, v; break
    if xv is None: xv = lb - max(K - float(pp.loc[xd,"close"]), 0.0)
    pnl = (xv - d0)*mult - 4*13.0
    return dict(symbol=root, entry_date=e, exit_date=xd, strike=K, dte=int(fdte),
                entry_iv=float("nan"), entry_delta=float("nan"), entry_credit=-d0*mult,
                pnl=pnl, pnl_pct_credit=pnl/(d0*mult), mae=worst,
                days_held=int((xd-e).days), exit_reason=reason, signal_type="")

vix = get_prices("^VIX","2012-01-01","2026-06-30")["close"]
rows=[]
for root in ("ES","CL","GC"):
    cont = gx.get_continuous(root, "2012-01-01", "2026-06-30")
    pp = _prep(cont); idx = pp.index
    p = f"data_cache/iv_series/{root}.parquet"
    if not os.path.exists(p): continue
    dl = pd.read_parquet(p); dl["date"]=pd.to_datetime(dl["date"]); dl=dl.set_index("date")
    arms = {"cal_cheap": (dl["iv_rank"]<=0.3)&(dl["spread"]<0)}
    if root=="ES":
        arms["cal_vix15"] = pd.Series(idx.map(lambda d: bool(vix.get(d, 99) < 15)), index=idx)
    for label, cond in arms.items():
        sig = pd.Series(idx.map(lambda d: bool(cond.get(d, False))), index=idx) if not isinstance(cond.index, pd.DatetimeIndex) or len(cond)!=len(idx) else cond
        ents, last = [], None
        for d in idx[sig.reindex(idx, fill_value=False)]:
            pos = idx.searchsorted(d)+1
            if pos >= len(idx): continue
            e = idx[pos]
            if last is None or (e-last).days >= 21:
                ents.append(e); last = e
        print(f"{root} {label}: {len(ents)} entries", flush=True)
        got=[]
        for e in ents:
            try:
                r = calendar(root, e, pp)
                if r: r["signal_type"]=label; got.append(r); rows.append(r)
            except Exception: pass
        if got:
            t=pd.DataFrame(got)
            print(f"  -> n={len(t)} win%={100*(t.pnl>0).mean():.0f} $/tr=${t.pnl.mean():,.0f} "
                  f"tot=${t.pnl.sum():,.0f} worst=${t.pnl.min():,.0f}", flush=True)
if rows:
    t=pd.DataFrame(rows)
    db.save_run(t, summarize(t), phase="calendar_h14", universe=sorted(t.symbol.unique()),
                start="2012-01-01", end="2026-06-30",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes="H14: ATM put calendar 30/90 same strike, cheap-vol entries, +40/-50/front-7DTE")
print("CALENDAR TEST DONE")
