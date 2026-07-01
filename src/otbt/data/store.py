"""Local historical-data store (cache-first).

Historical option data is immutable, so every Databento pull is persisted to
disk and re-read forever after. The API is only hit on a cache miss. This
makes re-runs (new signals, tweaked management, added hypotheses) cost $0.

Layout (parquet under data_cache/databento/):
    opra/definition/<SYMBOL>/<YYYY-MM-DD>.parquet
    opra/ohlcv1d_chain/<SYMBOL>/<YYYY-MM-DD>.parquet
    opra/inst/<INSTRUMENT_ID>__<START>__<END>.parquet

An empty result is still cached (as an empty frame) so we never re-pay to learn
"there was nothing here".
"""
from __future__ import annotations

import os

import pandas as pd

from ..config import DATA_CACHE_DIR

_BASE = os.path.join(DATA_CACHE_DIR, "databento")

# Simple in-process counters so a run can report cache hits vs billed misses.
STATS = {"hits": 0, "misses": 0}


def _path(*parts: str) -> str:
    p = os.path.join(_BASE, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _safe(name: str) -> str:
    return str(name).replace("/", "_").replace(":", "_")


def cached(rel_parts: tuple[str, ...], fetch_fn) -> pd.DataFrame:
    """Return cached parquet at the key, else call fetch_fn(), persist, return.

    fetch_fn must return a DataFrame (possibly empty). Only called on a miss.
    """
    path = _path(*[_safe(p) for p in rel_parts])
    if os.path.exists(path):
        STATS["hits"] += 1
        return pd.read_parquet(path)
    STATS["misses"] += 1
    df = fetch_fn()
    if df is None:
        df = pd.DataFrame()
    # persist (empty frames get a sentinel column so parquet round-trips)
    (df if not df.empty else pd.DataFrame({"__empty__": []})).to_parquet(path)
    return df


def is_cached(rel_parts: tuple[str, ...]) -> bool:
    return os.path.exists(_path(*[_safe(p) for p in rel_parts]))


def reset_stats() -> None:
    STATS["hits"] = STATS["misses"] = 0
