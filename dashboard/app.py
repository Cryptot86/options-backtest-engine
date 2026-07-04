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

tab_sum, tab_trades, tab_verify, tab_lab = st.tabs(
    ["📊 Summary", "📋 Trades", "🔎 Verify a trade", "🧪 Strategy Lab"])

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
    st.subheader("Verify a single trade")
    st.caption("Check the signal fired correctly, the strike/exit make sense, and "
               "the underlying path matches the recorded entry/exit.")
    fsym = st.selectbox("Symbol", sorted(trades["symbol"].unique()))
    sub = trades[trades["symbol"] == fsym].sort_values("entry_date")
    idx = st.selectbox(
        "Trade", sub.index,
        format_func=lambda i: f"{sub.loc[i,'entry_date'].date()} · {sub.loc[i,'signal_type']} "
                              f"· K {sub.loc[i,'strike']:.0f} · P&L ${sub.loc[i,'pnl']:.0f}")
    t = sub.loc[idx]

    m = st.columns(6)
    m[0].metric("Entry", str(t["entry_date"].date()))
    m[1].metric("Exit", str(t["exit_date"].date()))
    m[2].metric("Strike", f"${t['strike']:.0f}")
    m[3].metric("Credit", f"${t.get('entry_credit', float('nan')):.0f}")
    m[4].metric("P&L", f"${t['pnl']:.0f}")
    m[5].metric("Exit reason", str(t["exit_reason"]))

    px = get_prices(fsym, con_start, con_end)
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
                  annotation_text="put strike")
    fig.add_vline(x=t["entry_date"], line_color="#27ae60", annotation_text="entry")
    fig.add_vline(x=t["exit_date"], line_color="#c0392b", annotation_text="exit")
    fig.update_layout(height=460, title=f"{fsym} — {t['signal_type']}")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Put strike (dotted) should sit ~16Δ below entry; for bounce, exit "
               "should coincide with a close back below EMA100 if invalidated.")

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
