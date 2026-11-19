"""The ring never stops: Kiro circles it, picking a new random speed and direction every 3 seconds.

The motion comes from a seed, so the server and the page compute the same angle at the same
moment. static/app.js has the same functions; keep them in step.
"""

from __future__ import annotations

import math

SEGMENT = 3.0  # seconds between changes of speed and direction
_M = 0xFFFFFFFF


def _rnd(seed: int, k: int, salt: int) -> float:
    """A number in [0, 1) from (seed, segment, salt). Same bits as rnd() in app.js."""
    x = (seed ^ ((k * 0x9E3779B1) & _M) ^ ((salt * 0x85EBCA77) & _M)) & _M
    x ^= x >> 16
    x = (x * 0x7FEB352D) & _M
    x ^= x >> 15
    x = (x * 0x846CA68B) & _M
    x ^= x >> 16
    return x / 4294967296


def velocity(seed: int, k: int) -> float:
    """Radians per second during segment k: one lap every 10 to 20 seconds, either direction."""
    lap = 10 + 10 * _rnd(seed, k, 1)
    sign = -1 if _rnd(seed, k, 2) < 0.5 else 1
    return sign * 2 * math.pi / lap


def angle(seed: int, t0: float, base: float, t: float) -> float:
    """How far the ring has turned at time t, starting from `base` at time t0."""
    if t <= t0:
        return base
    a, cur, k = base, t0, 0
    while True:
        end = t0 + SEGMENT * (k + 1)
        if end >= t:
            return a + velocity(seed, k) * (t - cur)
        a += velocity(seed, k) * (end - cur)
        cur, k = end, k + 1
