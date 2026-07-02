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

tab_sum, tab_trades, tab_verify = st.tabs(["📊 Summary", "📋 Trades", "🔎 Verify a trade"])

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
