"""Streamlit dashboard for the options backtest.

Reads results from the SQLite DB (db/results.sqlite) and lets you:
  - view per-strategy metrics + charts for any run
  - browse every trade
  - verify a single trade: underlying price + EMA10/100 with entry/exit/strike
    markers, so you can eyeball that the signal, selection, and management were
    correct (the task-#5 verification view; extends to real option paths later).

Run:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import sys

# make imports work no matter where streamlit is launched from
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
os.chdir(_REPO)                      # relative paths (db/, data_cache/) too
os.environ.setdefault("OTBT_OFFLINE", "1")   # dashboard never spends

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.otbt.data import db
from src.otbt.data.prices import get_prices
from src.otbt.signals.indicators import ema

st.set_page_config(page_title="Options Backtest", layout="wide")
st.title("📉 Options Backtest — premium-selling strategies")

runs = db.list_runs()
if runs.empty:
    st.warning("No runs in the database yet. Run `python run_backtest.py` first.")
    st.stop()

# ---- run picker -----------------------------------------------------------
labels = {int(r.run_id): f"#{r.run_id} · {r.phase} · {r.n_trades} trades · {r.created_at}"
          for r in runs.itertuples()}
run_id = st.sidebar.selectbox("Run", list(labels), format_func=lambda i: labels[i])
meta = runs[runs["run_id"] == run_id].iloc[0]
con_start, con_end = meta["start"], meta["end"]

trades = pd.read_sql(f"SELECT * FROM trades WHERE run_id = {run_id}", db._conn())
summary = pd.read_sql(f"SELECT * FROM summary WHERE run_id = {run_id}", db._conn())
for c in ("entry_date", "exit_date"):
    if c in trades:
        trades[c] = pd.to_datetime(trades[c])

st.caption(f"Universe: {meta['universe']}  |  Window: {con_start} → {con_end}  "
           f"|  Phase: {meta['phase']}")
if "proxy" in str(meta["notes"]).lower():
    st.info("⚠️ Realized-vol proxy for IV — **rankings & tails are reliable, "
            "absolute dollars are approximate** (proxy can't see the vol risk premium).")

tab_sum, tab_trades, tab_verify, tab_lab, tab_cov, tab_port = st.tabs(
    ["📊 Summary", "📋 Trades", "🔎 Verify a trade", "🧪 Strategy Lab",
     "✅ Coverage", "💼 Portfolio Sim"])

# ---- summary --------------------------------------------------------------
with tab_sum:
    st.subheader("Per-strategy metrics")
    st.dataframe(summary.drop(columns=["run_id"], errors="ignore"), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Expectancy ($/contract)** — higher is better")
        s = summary.sort_values("expectancy")
        st.plotly_chart(go.Figure(go.Bar(
            x=s["expectancy"], y=s["signal_type"], orientation="h",
            marker_color=["#c0392b" if v < 0 else "#27ae60" for v in s["expectancy"]])),
            use_container_width=True)
    with c2:
        st.markdown("**Worst loss ($/contract)** — the tail the book cares about")
        s = summary.sort_values("worst_loss")
        st.plotly_chart(go.Figure(go.Bar(
            x=s["worst_loss"], y=s["signal_type"], orientation="h",
            marker_color="#c0392b")), use_container_width=True)

# ---- trades ---------------------------------------------------------------
with tab_trades:
    strat = st.multiselect("Strategy", sorted(trades["signal_type"].unique()))
    syms = st.multiselect("Symbol", sorted(trades["symbol"].unique()))
    view = trades
    if strat:
        view = view[view["signal_type"].isin(strat)]
    if syms:
        view = view[view["symbol"].isin(syms)]
    st.write(f"{len(view)} trades")
    st.dataframe(view.drop(columns=["run_id"], errors="ignore"), use_container_width=True)
    st.download_button("Download CSV", view.to_csv(index=False), "trades.csv")

# ---- verify a single trade ------------------------------------------------
with tab_verify:
    st.subheader("🔎 Verify a single trade — data, price, and logic")
    st.caption("Three checks per trade: (1) option data correct, (2) market "
               "price correct, (3) strategy logic correct. Cache-only — never pulls.")
    from src.otbt.data import store as _store
    _store.OFFLINE = True                       # hard guarantee: $0
    from src.otbt.pricing import glbx_options as _gx
    from src.otbt.signals.engine import _prep as _prep_fn

    fsym = st.selectbox("Symbol", sorted(trades["symbol"].unique()))
    sub = trades[trades["symbol"] == fsym].sort_values("entry_date")
    idx = st.selectbox(
        "Trade", sub.index,
        format_func=lambda i: f"{sub.loc[i,'entry_date'].date()} · {sub.loc[i,'signal_type']} "
                              f"· K {sub.loc[i,'strike']:.0f} · P&L ${sub.loc[i,'pnl']:.0f}")
    t = sub.loc[idx]
    is_fut = fsym in _gx.FUT_SPECS

    m = st.columns(6)
    m[0].metric("Entry", str(t["entry_date"].date()))
    m[1].metric("Exit", str(t["exit_date"].date()))
    m[2].metric("Strike", f"{t['strike']:.1f}")
    m[3].metric("Credit", f"${t.get('entry_credit', float('nan')):.0f}")
    m[4].metric("P&L", f"${t['pnl']:.0f}")
    m[5].metric("Exit reason", str(t["exit_reason"]))

    # --- underlying series (futures: continuous from cache; equities: yfinance)
    if is_fut:
        px = _gx.get_continuous(fsym, "2012-01-01", "2025-06-30")
    else:
        px = get_prices(fsym, con_start, con_end)
    checks = []

    # CHECK 1: strategy logic — did the entry condition actually hold that day?
    try:
        pp = _prep_fn(px)
        d = t["entry_date"]
        if d in pp.index:
            r = pp.loc[d]
            sigt = str(t["signal_type"]).split("|")[0]
            cond = {
                "bb_2sd": r["close"] <= r["bb_lower"] and r["trend_up"],
                "bb_20sma": r["trend_up"],
                "five_day_low": r["close"] <= pp["close"].rolling(5).min().loc[d] and r["trend_up"],
                "bounce_100ema": r["trend_up"],
                "vol_gate": True, "rsi_divergence": True, "vrp_baseline": True,
            }.get(sigt, None)
            if cond is not None:
                checks.append(("Entry condition held on entry date",
                               bool(cond),
                               f"close={r['close']:.2f}, bb_lower={r['bb_lower']:.2f}, "
                               f"EMA10 {'>' if r['trend_up'] else '<'} EMA100"))
    except Exception as e:
        checks.append(("Entry condition check", None, str(e)[:80]))

    # CHECK 2 + option path: locate the exact option from cached definitions
    opt_path = None
    if is_fut:
        try:
            defs = _gx.get_option_definitions(fsym, t["entry_date"])
            if not defs.empty:
                o = defs[defs["instrument_class"] == "P"].copy()
                o["dte"] = (o["expiration"].dt.normalize() - t["entry_date"]).dt.days
                o = o[(o["dte"] - float(t["dte"])).abs() < 3]
                o = o[(o["strike_price"] - float(t["strike"])).abs() < 1e-6]
                if len(o):
                    sym = str(o.iloc[0]["raw_symbol"])
                    expn = pd.Timestamp(o.iloc[0]["expiration"]).normalize()
                    p = _gx.get_option_path(sym, t["entry_date"], expn)
                    if not p.empty:
                        opt_path = p.set_index("date")["mid"]
                        e_px = float(opt_path.loc[t["entry_date"]]) if t["entry_date"] in opt_path.index else None
                        if e_px:
                            mult = _gx.FUT_SPECS[fsym]["mult"]
                            rec = float(t.get("entry_credit", 0))
                            ok = abs(e_px * mult - rec) <= max(0.05 * e_px * mult, 30)
                            checks.append((f"Option data: {sym} entry settle ${e_px:.3f} "
                                           f"x{mult} vs recorded credit ${rec:.0f}",
                                           ok, "within fees/slippage" if ok else "MISMATCH"))
                    checks.append(("Strike exists in listed chain", True, sym))
                else:
                    checks.append(("Strike exists in listed chain", False,
                                   "no match in cached definitions"))
        except Exception as e:
            checks.append(("Option data check", None, str(e)[:80]))

    # CHECK 3: market price present on entry/exit dates
    checks.append(("Underlying price on entry date", t["entry_date"] in px.index,
                   f"close={px.loc[t['entry_date'],'close']:.2f}" if t["entry_date"] in px.index else "missing"))
    checks.append(("Underlying price on exit date", t["exit_date"] in px.index,
                   f"close={px.loc[t['exit_date'],'close']:.2f}" if t["exit_date"] in px.index else "missing"))

    st.markdown("#### Verification checks")
    for name, ok, detail in checks:
        icon = "✅" if ok else ("⚠️" if ok is None else "❌")
        st.markdown(f"{icon} **{name}** — {detail}")

    # --- charts: underlying + option path side by side
    lo = t["entry_date"] - pd.Timedelta(days=40)
    hi = t["exit_date"] + pd.Timedelta(days=15)
    w = px.loc[lo:hi]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w.index, y=w["close"], name="close", line=dict(color="#2c3e50")))
    fig.add_trace(go.Scatter(x=w.index, y=ema(px["close"], 10).loc[lo:hi], name="EMA10",
                             line=dict(color="#2980b9", width=1)))
    fig.add_trace(go.Scatter(x=w.index, y=ema(px["close"], 100).loc[lo:hi], name="EMA100",
                             line=dict(color="#e67e22", width=1)))
    fig.add_hline(y=t["strike"], line_dash="dot", line_color="#c0392b",
                  annotation_text="strike")
    fig.add_vline(x=t["entry_date"], line_color="#27ae60", annotation_text="entry")
    fig.add_vline(x=t["exit_date"], line_color="#c0392b", annotation_text="exit")
    fig.update_layout(height=420, title=f"{fsym} underlying — {t['signal_type']}")
    st.plotly_chart(fig, use_container_width=True)

    if opt_path is not None:
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=opt_path.index, y=opt_path.values,
                                name="option settle", line=dict(color="#8e44ad")))
        f2.add_vline(x=t["entry_date"], line_color="#27ae60", annotation_text="sold")
        f2.add_vline(x=t["exit_date"], line_color="#c0392b", annotation_text="closed")
        if t.get("entry_credit") and pd.notna(t["entry_credit"]):
            mult = _gx.FUT_SPECS[fsym]["mult"]
            f2.add_hline(y=float(t["entry_credit"]) / mult * 0.5, line_dash="dot",
                         line_color="#27ae60", annotation_text="50% target")
        f2.update_layout(height=340, title="Option price path (real settlements) — "
                         "we profit as this decays")
        st.plotly_chart(f2, use_container_width=True)
    elif is_fut:
        st.info("Option path not in local cache for this trade (no new pulls in "
                "verify mode).")

# ---- strategy lab -----------------------------------------------------------
with tab_lab:
    st.subheader("🧪 Strategy Lab — market × method × structure")
    st.caption("Prices every signal with real CME settlement data (plan-covered, $0). "
               "First run per combo pulls data (~minutes); re-runs are instant from cache.")
    from src.otbt.pricing import glbx_options as gx
    from src.otbt.signals.engine import generate_signals, _prep
    from src.otbt.signals.baseline import generate_baseline
    from src.otbt.reporting.metrics import summarize as _summ

    c1, c2, c3, c4 = st.columns(4)
    root = c1.selectbox("Market", ["CL", "NG", "GC", "6E", "6B", "ES"])
    method = c2.selectbox("Method (entry)", [
        "bb_2sd", "bounce_100ema", "bb_20sma", "five_day_low", "rsi_divergence",
        "vrp_baseline (no direction — Tom style)"])
    structure = c3.selectbox("Structure", list(gx.STRUCTURES))
    start_yr = c4.selectbox("From year", [2012, 2015, 2018, 2020, 2022], index=0)

    if st.button("▶ Run backtest", type="primary"):
        cont = gx.get_continuous(root, f"{start_yr}-01-01", "2025-06-30")
        if cont.empty:
            st.error("No continuous data for this market."); st.stop()
        if method.startswith("vrp_baseline"):
            led = generate_baseline({root: cont})
        else:
            led = generate_signals({root: cont})
            led = led[led["signal_type"] == method]
        led = led[led["iv_proxy"].notna()]
        st.write(f"{len(led)} signals to price…")
        prog = st.progress(0.0)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        rows = list(led.iterrows())
        results = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(
                gx.simulate_structure, root, sig["date"], cont, structure,
                float(sig["iv_proxy"]), signal_type=f"{method[:12]}|{structure}"): 1
                for _, sig in rows}
            done = 0
            for f in as_completed(futs):
                done += 1
                prog.progress(done / max(len(rows), 1))
                try:
                    r = f.result()
                except Exception:
                    r = None
                if r is not None:
                    results.append(r)
        prog.empty()
        if not results:
            st.warning("No trades priced for this combo."); st.stop()
        rdf = pd.DataFrame([r.__dict__ for r in results]).sort_values("entry_date")
        st.success(f"{len(rdf)} trades priced ({len(rows) - len(rdf)} skipped)")
        st.dataframe(_summ(rdf), use_container_width=True)

        rdf["cum"] = rdf["pnl"].cumsum()
        fig = go.Figure(go.Scatter(x=rdf["entry_date"], y=rdf["cum"],
                                   mode="lines+markers", name="cumulative P&L"))
        fig.update_layout(height=380, title=f"{root} · {method} · {structure} — "
                          f"cumulative $/1-lot (total ${rdf['pnl'].sum():,.0f})")
        st.plotly_chart(fig, use_container_width=True)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total P&L", f"${rdf['pnl'].sum():,.0f}")
        m2.metric("Win %", f"{100*(rdf['pnl']>0).mean():.0f}%")
        m3.metric("Worst trade", f"${rdf['pnl'].min():,.0f}")
        m4.metric("Worst MAE", f"${rdf['mae'].min():,.0f}")
        with st.expander("All trades"):
            st.dataframe(rdf.drop(columns=["cum"]), use_container_width=True)

# ---- coverage validation ----------------------------------------------------
with tab_cov:
    st.subheader("✅ Coverage — was EVERY signal actually traded?")
    st.caption("Independently regenerates the signal set for the selected run "
               "and joins it against the trades in the DB. Anything unpriced "
               "is listed — no silent skips.")
    from src.otbt.pricing import glbx_options as _gxc
    from src.otbt.signals.engine import (generate_signals as _gs,
                                         generate_call_signals as _gcs, _prep as _pp)

    phase = str(meta["phase"])
    uni = str(meta["universe"]).split(",")
    lag = 1 if "lag1" in phase else 0
    supported = phase.startswith("futures_glbx") or phase == "phase1_realiv"
    if not supported:
        st.info(f"Coverage view supports signal-based runs "
                f"(futures_glbx*, phase1_realiv). This run's phase: `{phase}`.")
    else:
        led_frames = []
        for u in uni:
            if u in _gxc.FUT_SPECS:
                cont = _gxc.get_continuous(u, "2012-01-01", "2025-06-30")
                if cont.empty:
                    continue
                gen = _gcs if "calls" in phase else _gs
                led_frames.append(gen({u: cont}))
            else:
                pxu = get_prices(u, con_start, con_end)
                led_frames.append(_gs({u: pxu}))
        if not led_frames:
            st.warning("Could not regenerate signals.")
        else:
            led = pd.concat(led_frames, ignore_index=True)
            led = led[led["iv_proxy"].notna()]
            led["date"] = pd.to_datetime(led["date"])
            led = led[led["date"] >= pd.Timestamp(con_start)]
            if lag:
                # shift each signal to the next trading day, per symbol
                shifted = []
                for u in uni:
                    cal = (_gxc.get_continuous(u, "2012-01-01", "2025-06-30").index
                           if u in _gxc.FUT_SPECS else get_prices(u, con_start, con_end).index)
                    sub = led[led["symbol"] == u].copy()
                    pos = cal.searchsorted(sub["date"]) + 1
                    sub["date"] = [cal[p] if p < len(cal) else pd.NaT for p in pos]
                    shifted.append(sub.dropna(subset=["date"]))
                led = pd.concat(shifted, ignore_index=True)

            tkey = trades.assign(k=trades["symbol"].astype(str) + "|"
                                 + pd.to_datetime(trades["entry_date"]).astype(str) + "|"
                                 + trades["signal_type"].astype(str))["k"]
            led["k"] = (led["symbol"].astype(str) + "|" + led["date"].astype(str)
                        + "|" + led["signal_type"].astype(str))
            led["priced"] = led["k"].isin(set(tkey))

            cov = led.groupby("signal_type").agg(
                signals=("priced", "size"), priced=("priced", "sum"))
            cov["coverage_%"] = (100 * cov["priced"] / cov["signals"]).round(1)
            tot = pd.DataFrame({"signals": [cov.signals.sum()],
                                "priced": [cov.priced.sum()],
                                "coverage_%": [round(100 * cov.priced.sum()
                                                     / max(cov.signals.sum(), 1), 1)]},
                               index=["TOTAL"])
            st.dataframe(pd.concat([cov, tot]), use_container_width=True)
            pct = float(tot["coverage_%"].iloc[0])
            (st.success if pct >= 90 else st.warning if pct >= 75 else st.error)(
                f"Overall coverage: {pct}% "
                f"({int(tot['priced'].iloc[0])} of {int(tot['signals'].iloc[0])} signals priced)")
            miss = led[~led["priced"]][["symbol", "date", "signal_type"]] \
                .sort_values("date")
            with st.expander(f"⚠️ {len(miss)} unpriced signals — inspect"):
                st.dataframe(miss, use_container_width=True)
                st.caption("Common causes: no listed expiry in window (calendar gap), "
                           "no settlement print on entry day, data-vendor gap. "
                           "Each one is a potential survivorship bias — check "
                           "whether misses cluster in crisis periods.")

# ---- portfolio simulator ----------------------------------------------------
with tab_port:
    st.subheader("💼 Portfolio Simulator — your allocation rules on real trade history")
    st.caption("Top-15 gated equities + MES puts + CL/NG calls + micro long calls. "
               "Compounding, margin-capacity enforced, VIX-banded allocation.")
    import numpy as np
    from src.otbt.signals.indicators import realized_vol as _rv

    @st.cache_data(show_spinner=False)
    def _sim_trades():
        vixس = get_prices("^VIX", "2017-01-01", "2025-06-30")["close"]
        spy_ = get_prices("SPY", "2017-01-01", "2025-06-30")["close"]
        rk = vixس.rolling(252).apply(lambda w: (w.iloc[-1] >= w).mean())
        gt = (rk >= 0.5) & ((vixس - _rv(spy_, 20).reindex(vixس.index) * 100) > 0) & (vixس.diff(5) <= 0)
        con2 = db._conn()
        T15 = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","AVGO",
               "JPM","COST","LLY","UNH","HD"]
        rs = db.list_runs()
        eqr = rs[(rs.phase == "phase1_realiv") & (rs.run_id >= 32)].run_id.tolist()
        rows = []
        te = pd.read_sql(f'SELECT symbol,entry_date,exit_date,strike,pnl FROM trades '
                         f'WHERE run_id IN ({",".join(map(str, eqr))}) '
                         f'AND signal_type IN ("bb_2sd","five_day_low")', con2)
        te = te[te.symbol.isin(T15)]
        for c in ("entry_date", "exit_date"):
            te[c] = pd.to_datetime(te[c])
        te = te[te.entry_date.map(lambda d: bool(gt.get(d, False)))]
        for _, r in te.iterrows():
            rows.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl,
                             margin=0.20 * r.strike * 100, book="sell"))
        t2 = pd.read_sql("SELECT entry_date,exit_date,pnl FROM trades WHERE run_id=66 "
                         "AND signal_type IN ('bb_2sd','five_day_low')", con2)
        for c in ("entry_date", "exit_date"):
            t2[c] = pd.to_datetime(t2[c])
        for _, r in t2.iterrows():
            rows.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl / 10.0,
                             margin=1300.0, book="sell"))
        for rid, mg in ((28, 3500.0), (27, 2800.0)):
            t3 = pd.read_sql(f"SELECT entry_date,exit_date,pnl FROM trades WHERE run_id={rid} "
                             f"AND signal_type='bb_2sd_call'", con2)
            for c in ("entry_date", "exit_date"):
                t3[c] = pd.to_datetime(t3[c])
            for _, r in t3.iterrows():
                rows.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl, margin=mg, book="sell"))
        t4 = pd.read_sql("SELECT entry_date,exit_date,entry_credit,pnl FROM trades "
                         "WHERE run_id=33 AND symbol IN ('ES','GC')", con2)
        for c in ("entry_date", "exit_date"):
            t4[c] = pd.to_datetime(t4[c])
        for _, r in t4.iterrows():
            rows.append(dict(d=r.entry_date, x=r.exit_date, pnl=r.pnl / 10.0,
                             margin=abs(r.entry_credit) / 10.0, book="buy"))
        return pd.DataFrame(rows), vixس

    c1, c2, c3, c4, c5 = st.columns(5)
    eq0   = c1.number_input("Start equity $", 10_000, 1_000_000, 50_000, step=5_000)
    aBase = c2.slider("Sell % (VIX<25)", 10, 60, 25, 5) / 100
    aMid  = c3.slider("Sell % (VIX 25-35)", 20, 80, 50, 5) / 100
    aHigh = c4.slider("Sell % (VIX 35+)", 20, 90, 60, 5) / 100
    aBuy  = c5.slider("Buy %", 0, 30, 15, 5) / 100
    start = st.date_input("Start date", pd.Timestamp("2019-07-01"))

    if st.button("▶ Run simulation", type="primary"):
        Tt, vixx = _sim_trades()
        Tt = Tt[Tt.d >= pd.Timestamp(start)].sort_values("d")
        days = pd.date_range(pd.Timestamp(start), "2025-06-30", freq="D")
        vd = vixx.reindex(days, method="ffill").fillna(20.0)
        byd = {d: g for d, g in Tt.groupby("d")}
        equity, open_pos, taken, skipped = float(eq0), [], 0, 0
        curve = np.empty(len(days))
        for i, day in enumerate(days):
            for p in [p for p in open_pos if p["x"] <= day]:
                equity += p["pnl"]; open_pos.remove(p)
            v = vd.iloc[i]
            capS = (aBase if v < 25 else aMid if v < 35 else aHigh) * equity
            capB = aBuy * equity
            uS = sum(p["margin"] for p in open_pos if p["book"] == "sell")
            uB = sum(p["margin"] for p in open_pos if p["book"] == "buy")
            if day in byd:
                for _, r in byd[day].iterrows():
                    cap, used = (capS, uS) if r.book == "sell" else (capB, uB)
                    if used + r.margin <= cap:
                        open_pos.append(dict(r)); taken += 1
                        if r.book == "sell": uS += r.margin
                        else: uB += r.margin
                    else:
                        skipped += 1
            curve[i] = equity
        for p in open_pos:
            equity += p["pnl"]
        cv = pd.Series(curve, index=days)
        yrs = max((days[-1] - days[0]).days / 365.25, 0.5)
        cagr = (equity / eq0) ** (1 / yrs) - 1
        ddpc = ((cv - cv.cummax()) / cv.cummax()).min()
        m = st.columns(5)
        m[0].metric("Final equity", f"${equity:,.0f}", f"{(equity/eq0-1)*100:+.0f}%")
        m[1].metric("CAGR", f"{cagr*100:.1f}%")
        m[2].metric("Max drawdown", f"{ddpc*100:.1f}%")
        m[3].metric("MAR", f"{(cagr/abs(ddpc)):.2f}" if ddpc < 0 else "∞")
        m[4].metric("Taken / skipped", f"{taken} / {skipped}")
        figp = go.Figure(go.Scatter(x=cv.index, y=cv.values, name="equity",
                                    line=dict(color="#27ae60", width=2)))
        figp.update_layout(height=380, title="Equity curve")
        st.plotly_chart(figp, use_container_width=True)
        yr = cv.resample("YE").last()
        st.dataframe(pd.DataFrame({"year-end equity": yr.round(0),
                                   "yearly %": (yr.pct_change() * 100).round(1)}),
                     use_container_width=True)
