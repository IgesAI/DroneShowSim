from __future__ import annotations

import math

import numpy as np

from app.safety.geometry import AIR_FLOOR_Z, PAD_Z, flight_floor
from app.trajectory.minjerk import min_jerk

PATH_SCALE = {
    "explode": 1.25,
    "orbit": 1.35,
    "wave": 1.12,
}


def ease(u: float, style: str) -> float:
    return u if style == "direct" else min_jerk(u)


def evaluate_segment(p0: np.ndarray, p1: np.ndarray, u: float, style: str) -> np.ndarray:
    s = ease(u, style)
    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    if style == "explode":
        mid = (a + b) * 0.5
        mid = mid + np.array([a[0] * 0.35, 0.0, 8.0])
        o = 1.0 - s
        p = a * o * o + mid * 2.0 * o * s + b * s * s
        p[2] = max(float(p[2]), flight_floor(float(a[2]), float(b[2])))
        return p
    if style == "orbit":
        p = _orbit_at(a, b, s)
        p[2] = max(float(p[2]), flight_floor(float(a[2]), float(b[2])))
        return p
    if style == "wave":
        p = a + s * (b - a)
        p[2] += math.sin(s * math.pi) * 6.0
    else:
        p = a + s * (b - a)
    p = np.asarray(p, dtype=np.float64)
    p[2] = max(float(p[2]), flight_floor(float(a[2]), float(b[2])))
    return p


def _clamp_airborne(pos: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    lo = np.minimum(p0[:, 2], p1[:, 2])
    pad = (lo >= -1e-6) & (lo <= PAD_Z + 0.25)
    floor = np.where(pad, 0.0, AIR_FLOOR_Z)
    pos[:, :, 2] = np.maximum(pos[:, :, 2], floor[None, :])
    return pos


def sample_transition(p0: np.ndarray, p1: np.ndarray, u: np.ndarray, style: str) -> np.ndarray:
    """p0/p1: (n,3), u: (f,) → (f,n,3). umap/stagger/collapse/auto fall through to morph."""
    if style == "direct":
        s = u
    else:
        s = u**3 * (10.0 + u * (-15.0 + 6.0 * u))
    if style == "explode":
        mid = (p0 + p1) * 0.5
        mid = mid.copy()
        mid[:, 0] = mid[:, 0] + p0[:, 0] * 0.35
        mid[:, 2] = mid[:, 2] + 8.0
        o = 1.0 - s
        pos = o[:, None, None] ** 2 * p0 + (2.0 * o * s)[:, None, None] * mid + (s**2)[:, None, None] * p1
    elif style == "orbit":
        pos = np.empty((len(s), len(p0), 3), dtype=np.float64)
        for i in range(len(p0)):
            for fi, si in enumerate(s):
                pos[fi, i] = _orbit_at(p0[i], p1[i], float(si))
    elif style == "wave":
        pos = p0[None, :, :] + s[:, None, None] * (p1 - p0)[None, :, :]
        pos[:, :, 2] = pos[:, :, 2] + np.sin(s * math.pi)[:, None] * 6.0
    else:
        pos = p0[None, :, :] + s[:, None, None] * (p1 - p0)[None, :, :]
    return _clamp_airborne(pos, p0, p1)


def _orbit_at(a: np.ndarray, b: np.ndarray, s: float) -> np.ndarray:
    mx = (a[0] + b[0]) * 0.5
    my = (a[1] + b[1]) * 0.5
    a0 = math.atan2(a[1] - my, a[0] - mx)
    a1 = math.atan2(b[1] - my, b[0] - mx)
    da = a1 - a0
    if da > math.pi:
        da -= math.tau
    elif da < -math.pi:
        da += math.tau
    r0 = math.hypot(a[0] - mx, a[1] - my)
    r1 = math.hypot(b[0] - mx, b[1] - my)
    if r0 < 1e-6 and r1 < 1e-6:
        return a + s * (b - a)
    r = r0 + (r1 - r0) * s
    ang = a0 + da * s
    return np.array([mx + math.cos(ang) * r, my + math.sin(ang) * r, a[2] + (b[2] - a[2]) * s])
