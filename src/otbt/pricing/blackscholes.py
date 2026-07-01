"""Black-Scholes (equities) and Black-76 (options on futures) pricing.

Used two ways:
  1. Phase-0 P&L reconstruction from underlying paths + realized-vol proxy.
  2. Delta<->strike solving when selecting the 16-delta strike, and as a
     cross-check against real Databento option marks in Layer 2.

Rates default to ~0; for short-dated premium the carry term is negligible and
the charter's dollar-expectancy precision comes from real IV, not r.
"""
from __future__ import annotations

import math

from scipy.stats import norm


SQRT = math.sqrt


def _d1_d2(S: float, K: float, T: float, sigma: float, r: float, q: float):
    if T <= 0 or sigma <= 0:
        raise ValueError("T and sigma must be positive")
    vol_t = sigma * SQRT(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def bs_price(S, K, T, sigma, r=0.0, q=0.0, kind="put") -> float:
    """Black-Scholes price for a European option on a spot asset (with yield q)."""
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    if kind == "call":
        return S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    return K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)


def bs_delta(S, K, T, sigma, r=0.0, q=0.0, kind="put") -> float:
    d1, _ = _d1_d2(S, K, T, sigma, r, q)
    disc_q = math.exp(-q * T)
    if kind == "call":
        return disc_q * norm.cdf(d1)
    return -disc_q * norm.cdf(-d1)


def b76_price(F, K, T, sigma, r=0.0, kind="put") -> float:
    """Black-76 price for a European option on a futures price F."""
    d1, d2 = _d1_d2(F, K, T, sigma, r, q=0.0)
    disc = math.exp(-r * T)
    if kind == "call":
        return disc * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return disc * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def b76_delta(F, K, T, sigma, r=0.0, kind="put") -> float:
    d1, _ = _d1_d2(F, K, T, sigma, r, q=0.0)
    disc = math.exp(-r * T)
    if kind == "call":
        return disc * norm.cdf(d1)
    return -disc * norm.cdf(-d1)


def strike_for_delta(S, T, sigma, target_delta=0.16, r=0.0, q=0.0,
                     kind="put", futures=False) -> float:
    """Solve for the strike whose |delta| == target_delta.

    Monotone in K, so a bisection is robust. Returns the strike (not rounded
    to a listed increment — Layer 2 snaps to the nearest listed strike).
    """
    target = abs(target_delta)
    delta_fn = (lambda K: b76_delta(S, K, T, sigma, r, kind)) if futures \
        else (lambda K: bs_delta(S, K, T, sigma, r, q, kind))

    lo, hi = 1e-6 * S, 5.0 * S          # wide bracket around spot/future
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        d = abs(delta_fn(mid))
        # For puts |delta| increases with K; for calls it decreases with K.
        if kind == "put":
            if d > target:
                hi = mid
            else:
                lo = mid
        else:
            if d > target:
                lo = mid
            else:
                hi = mid
        if abs(d - target) < 1e-6:
            break
    return 0.5 * (lo + hi)
