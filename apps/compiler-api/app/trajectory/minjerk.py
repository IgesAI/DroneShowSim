from __future__ import annotations

import numpy as np

# s(u) = 10u^3 - 15u^4 + 6u^5
# peak |s'| ≈ 1.875 at u=0.5
# peak |s''| ≈ 5.77 near u=0.211 / 0.789
PEAK_S1 = 1.875
PEAK_S2 = 5.77


def min_jerk(u: float) -> float:
    x = min(1.0, max(0.0, u))
    return x * x * x * (10.0 + x * (-15.0 + 6.0 * x))


def min_duration(distance: float, vmax: float, amax: float) -> float:
    tv = PEAK_S1 * distance / max(vmax, 0.1)
    ta = (PEAK_S2 * distance / max(amax, 0.1)) ** 0.5
    return max(tv, ta, 0.4)


def evaluate(p0: np.ndarray, p1: np.ndarray, u: float) -> np.ndarray:
    return p0 + min_jerk(u) * (p1 - p0)


def sample_transition(
    p0: np.ndarray,
    p1: np.ndarray,
    duration: float,
    hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames = max(2, int(duration * hz) + 1)
    t = np.linspace(0.0, duration, frames)
    u = t / max(duration, 1e-6)
    s = u**3 * (10 + u * (-15 + 6 * u))
    pos = p0[None, :] + s[:, None] * (p1 - p0)[None, :]
    vel = np.gradient(pos, t, axis=0)
    acc = np.gradient(vel, t, axis=0)
    return pos, vel, acc
