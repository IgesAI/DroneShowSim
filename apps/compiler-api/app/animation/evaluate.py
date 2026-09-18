from __future__ import annotations

import math

import numpy as np

from app.models import AnimationClip
from app.safety.geometry import AIR_FLOOR_Z, PAD_Z
from app.trajectory.minjerk import min_jerk


def apply_motion(points: np.ndarray, clip: AnimationClip, u: float) -> np.ndarray:
    e = min_jerk(min(1.0, max(0.0, u)))
    c = points.mean(axis=0)
    rel = points - c
    out = points.copy()
    if clip.motion == "backflip":
        a = e * math.tau
        ca, sa = math.cos(a), math.sin(a)
        out[:, 1] = c[1] + rel[:, 1] * ca - rel[:, 2] * sa
        out[:, 2] = c[2] + rel[:, 1] * sa + rel[:, 2] * ca
    elif clip.motion in {"orbit", "yaw"}:
        a = e * math.tau
        ca, sa = math.cos(a), math.sin(a)
        out[:, 0] = c[0] + rel[:, 0] * ca - rel[:, 1] * sa
        out[:, 1] = c[1] + rel[:, 0] * sa + rel[:, 1] * ca
    elif clip.motion == "advance":
        out[:, 1] = points[:, 1] + e * 18.0 * clip.amplitude
    elif clip.motion == "wave":
        out[:, 2] = points[:, 2] + np.sin(u * math.tau + points[:, 0] * 0.12) * 4.0 * clip.amplitude
    elif clip.motion == "flap":
        wing = np.sign(rel[:, 0])
        wing[wing == 0] = 1.0
        out[:, 2] = points[:, 2] + np.sin(u * math.tau) * 6.0 * clip.amplitude * np.abs(rel[:, 0]) * 0.04 * wing
    elif clip.motion == "pulse":
        s = 1.0 + math.sin(u * math.tau) * 0.12 * clip.amplitude
        out = c + rel * s
    pad = (points[:, 2] >= -1e-6) & (points[:, 2] <= PAD_Z + 0.25)
    floor = np.where(pad, 0.0, AIR_FLOOR_Z)
    out[:, 2] = np.maximum(out[:, 2], floor)
    return out


def apply_color(colors: np.ndarray, clip: AnimationClip, u: float) -> np.ndarray:
    if clip.motion != "chroma":
        return colors
    s = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(u * math.tau)) * clip.amplitude
    return np.clip(colors * s, 0.0, 1.0)


def local_u(clip: AnimationClip, t: float) -> float | None:
    span = max(clip.duration, 1e-6)
    raw = (t - clip.startTime) / span
    if clip.loop:
        if t < clip.startTime:
            return None
        return raw % 1.0
    if raw < 0.0 or raw > 1.0:
        return None
    return raw
