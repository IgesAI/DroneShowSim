from __future__ import annotations

import numpy as np

EPS = 1e-9
PAD_Z = 0.12
AIR_FLOOR_Z = 1.0


def flight_floor(z0: float, z1: float | None = None, ground_z: float = 0.0) -> float:
    """Pads may sit on the dirt. In-flight (or leftover underground) stays ≥ 1 m AGL."""
    lo = z0 if z1 is None else min(z0, z1)
    if ground_z - 1e-6 <= lo <= ground_z + PAD_Z + 0.25:
        return ground_z
    return ground_z + AIR_FLOOR_Z


def clamp_altitude(z: float, floor_z: float) -> float:
    return z if z >= floor_z else floor_z


def segment_distance(a0: np.ndarray, a1: np.ndarray, b0: np.ndarray, b1: np.ndarray) -> tuple[float, float]:
    """Closest distance between two 3D segments and the parametric time on A in [0,1]."""
    a = a1 - a0
    b = b1 - b0
    r = a0 - b0
    aa = float(np.dot(a, a))
    ee = float(np.dot(b, b))
    ff = float(np.dot(b, r))
    if aa <= EPS and ee <= EPS:
        return float(np.linalg.norm(a0 - b0)), 0.0
    if aa <= EPS:
        t = min(1.0, max(0.0, ff / ee))
        return float(np.linalg.norm(a0 - (b0 + t * b))), 0.0
    cc = float(np.dot(a, r))
    if ee <= EPS:
        s = min(1.0, max(0.0, -cc / aa))
        return float(np.linalg.norm(a0 + s * a - b0)), s
    bb = float(np.dot(a, b))
    denom = aa * ee - bb * bb
    if denom > EPS:
        s = min(1.0, max(0.0, (bb * ff - cc * ee) / denom))
    else:
        s = 0.0
    t = (bb * s + ff) / ee
    if t < 0.0:
        t = 0.0
        s = min(1.0, max(0.0, -cc / aa))
    elif t > 1.0:
        t = 1.0
        s = min(1.0, max(0.0, (bb - cc) / aa))
    p = a0 + s * a
    q = b0 + t * b
    return float(np.linalg.norm(p - q)), s


def closing_speed(p_i: np.ndarray, p_j: np.ndarray, v_i: np.ndarray, v_j: np.ndarray) -> float:
    delta = p_j - p_i
    dist = float(np.linalg.norm(delta))
    if dist < EPS:
        return float(np.linalg.norm(v_i - v_j))
    return max(0.0, float(np.dot(v_i - v_j, delta / dist)))


def closing_speeds(p_i: np.ndarray, p_j: np.ndarray, v_i: np.ndarray, v_j: np.ndarray) -> np.ndarray:
    delta = p_j - p_i
    dist = np.linalg.norm(delta, axis=1)
    rel = v_i - v_j
    out = np.linalg.norm(rel, axis=1)
    ok = dist >= EPS
    out[ok] = np.maximum(0.0, np.sum(rel[ok] * (delta[ok] / dist[ok, None]), axis=1))
    return out


def segment_distances(
    a0: np.ndarray,
    a1: np.ndarray,
    b0: np.ndarray,
    b1: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Closest distances between paired 3D segments. a0..b1 are (k, 3)."""
    if len(a0) == 0:
        z = np.zeros(0, dtype=np.float64)
        return z, z
    a = a1 - a0
    b = b1 - b0
    r = a0 - b0
    aa = np.einsum("ij,ij->i", a, a)
    ee = np.einsum("ij,ij->i", b, b)
    ff = np.einsum("ij,ij->i", b, r)
    cc = np.einsum("ij,ij->i", a, r)
    bb = np.einsum("ij,ij->i", a, b)
    s = np.zeros(len(a0), dtype=np.float64)
    t = np.zeros(len(a0), dtype=np.float64)

    both_pt = (aa <= EPS) & (ee <= EPS)
    a_pt = (aa <= EPS) & ~both_pt
    b_pt = (ee <= EPS) & ~both_pt
    seg = ~both_pt & ~a_pt & ~b_pt

    if np.any(a_pt):
        t[a_pt] = np.clip(ff[a_pt] / ee[a_pt], 0.0, 1.0)
    if np.any(b_pt):
        s[b_pt] = np.clip(-cc[b_pt] / aa[b_pt], 0.0, 1.0)
    if np.any(seg):
        denom = aa[seg] * ee[seg] - bb[seg] * bb[seg]
        s_seg = np.zeros(int(seg.sum()), dtype=np.float64)
        wide = denom > EPS
        tmp = np.zeros_like(s_seg)
        tmp[wide] = (bb[seg][wide] * ff[seg][wide] - cc[seg][wide] * ee[seg][wide]) / denom[wide]
        s_seg = np.clip(tmp, 0.0, 1.0)
        t_seg = (bb[seg] * s_seg + ff[seg]) / ee[seg]
        low = t_seg < 0.0
        high = t_seg > 1.0
        t_seg = np.clip(t_seg, 0.0, 1.0)
        s_seg[low] = np.clip(-cc[seg][low] / aa[seg][low], 0.0, 1.0)
        s_seg[high] = np.clip((bb[seg][high] - cc[seg][high]) / aa[seg][high], 0.0, 1.0)
        s[seg] = s_seg
        t[seg] = t_seg

    p = a0 + s[:, None] * a
    q = b0 + t[:, None] * b
    return np.linalg.norm(p - q, axis=1), s


def swept_distances(
    a0: np.ndarray,
    a1: np.ndarray,
    b0: np.ndarray,
    b1: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Closest approach of two aircraft moving simultaneously over one frame.

    This is not the distance between their paths. `segment_distances` lets one
    drone sit at the start of its segment while the other is at the end, so two
    aircraft that fly the same corridor a minute apart register as nearly
    touching. Separation is a question about a shared instant, so both endpoints
    advance together: the gap is |w0 + u*dw| for one u, minimised in closed form.
    """
    if len(a0) == 0:
        z = np.zeros(0, dtype=np.float64)
        return z, z
    w0 = a0 - b0
    dw = (a1 - b1) - w0
    denom = np.einsum("ij,ij->i", dw, dw)
    u = np.zeros(len(a0), dtype=np.float64)
    moving = denom > EPS
    u[moving] = np.clip(
        -np.einsum("ij,ij->i", w0[moving], dw[moving]) / denom[moving], 0.0, 1.0
    )
    return np.linalg.norm(w0 + u[:, None] * dw, axis=1), u
