"""Sampling is an output stage, never the canonical representation.

Programs stay continuous and semantic; these helpers flatten them for the
viewport, validation and export only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.choreography.tracks import VISUAL_THRESHOLD, DroneProgram, RoleType

ROLE_CODES: dict[RoleType, int] = {
    "FORMATION": 0,
    "EFFECT": 1,
    "STAGING": 2,
    "RESERVE": 3,
    "TAKEOFF": 4,
    "RTH": 5,
}
CODE_ROLES = {v: k for k, v in ROLE_CODES.items()}

# Engineering-view classes
CLASS_VISIBLE = 0
CLASS_DARK_STAGING = 1
CLASS_EFFECT = 2
CLASS_RESERVE = 3


@dataclass
class SampledShow:
    times: np.ndarray  # (F,)
    positions: np.ndarray  # (F, N, 3)
    velocities: np.ndarray  # (F, N, 3)
    accelerations: np.ndarray  # (F, N, 3)
    colors: np.ndarray  # (F, N, 3) linear rgb
    brightness: np.ndarray  # (F, N)
    roles: np.ndarray  # (F, N) int codes
    droneIds: list[int]

    @property
    def frames(self) -> int:
        return len(self.times)

    @property
    def count(self) -> int:
        return len(self.droneIds)


def _sample_trajectory(
    program: DroneProgram, times: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Position, velocity and acceleration, all analytic.

    Derivatives come from the segments themselves rather than from
    differencing the sampled positions. Differencing a 0.125 s grid three
    times to recover jerk measures the grid, not the aircraft: on this show it
    reported 15 m/s³ against a 6 m/s³ limit for a flight whose true peak was
    under 2.
    """
    segs = program.trajectoryTrack.sorted_segments()
    f = len(times)
    if not segs:
        return np.zeros((f, 3)), np.zeros((f, 3)), np.zeros((f, 3))

    starts = np.array([s.startTime for s in segs], dtype=np.float64)
    durs = np.maximum(np.array([s.duration for s in segs], dtype=np.float64), 1e-9)
    p0 = np.array([s.start for s in segs], dtype=np.float64)
    p1 = np.array([s.end for s in segs], dtype=np.float64)
    floor = np.array([s.floorZ for s in segs], dtype=np.float64)
    hold = np.array([s.style == "hold" for s in segs])
    linear = np.array([s.style == "linear" for s in segs])
    curved = np.array([s.style == "spline" and bool(s.waypoints) for s in segs])

    idx = np.clip(np.searchsorted(starts, times, side="right") - 1, 0, len(segs) - 1)
    u = np.clip((times - starts[idx]) / durs[idx], 0.0, 1.0)

    s = u**3 * (10.0 + u * (-15.0 + 6.0 * u))
    ds = u**2 * (30.0 + u * (-60.0 + 30.0 * u))
    dds = u * (60.0 + u * (-180.0 + 120.0 * u))
    s = np.where(linear[idx], u, s)
    ds = np.where(linear[idx], 1.0, ds)
    dds = np.where(linear[idx] | hold[idx], 0.0, dds)
    s = np.where(hold[idx], 0.0, s)
    ds = np.where(hold[idx], 0.0, ds)

    delta = p1[idx] - p0[idx]
    pos = p0[idx] + s[:, None] * delta
    pos[:, 2] = np.maximum(pos[:, 2], floor[idx])

    inside = (times >= starts[idx] - 1e-9) & (times <= starts[idx] + durs[idx] + 1e-9)
    vel = delta * (ds / durs[idx])[:, None]
    acc = delta * (dds / (durs[idx] * durs[idx]))[:, None]
    vel[~inside] = 0.0
    acc[~inside] = 0.0

    # Splines carry interior knots, so the closed forms above do not describe
    # them. They are a small minority of segments; evaluate those frames one
    # at a time rather than slowing the common path down.
    if curved.any():
        for k in np.nonzero(curved[idx])[0]:
            seg = segs[int(idx[k])]
            t = float(times[k])
            pos[k] = seg.position(t)
            vel[k] = seg.velocity(t)
            acc[k] = seg.acceleration(t)
    return pos, vel, acc


def _sample_lighting(program: DroneProgram, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    keys = program.lightingTrack.keyframes
    f = len(times)
    if not keys:
        return np.ones((f, 3)), np.ones(f)

    kt = np.array([k.time for k in keys], dtype=np.float64)
    rgb = np.array([k.rgbLinear for k in keys], dtype=np.float64)
    bri = np.array([k.brightness for k in keys], dtype=np.float64)
    step = np.array([k.interpolation == "step" for k in keys])

    i = np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(keys) - 1)
    j = np.clip(i + 1, 0, len(keys) - 1)
    span = np.maximum(kt[j] - kt[i], 1e-9)
    u = np.clip((times - kt[i]) / span, 0.0, 1.0)
    u = np.where(step[i] | (j == i), 0.0, u)

    color = rgb[i] + u[:, None] * (rgb[j] - rgb[i])
    brightness = np.clip(bri[i] + u * (bri[j] - bri[i]), 0.0, 1.0)
    return color, brightness


def _sample_roles(program: DroneProgram, times: np.ndarray) -> np.ndarray:
    segs = program.roleTrack.segments
    if not segs:
        return np.full(len(times), ROLE_CODES["RESERVE"], dtype=np.int8)
    ordered = sorted(segs, key=lambda s: s.startTime)
    starts = np.array([s.startTime for s in ordered], dtype=np.float64)
    ends = np.array([s.endTime for s in ordered], dtype=np.float64)
    codes = np.array([ROLE_CODES.get(s.roleType, 3) for s in ordered], dtype=np.int8)
    idx = np.clip(np.searchsorted(starts, times, side="right") - 1, 0, len(ordered) - 1)
    out = codes[idx]
    out[times > ends[idx] + 1e-6] = ROLE_CODES["RESERVE"]
    return out


def sample_programs(programs: list[DroneProgram], times: np.ndarray) -> SampledShow:
    n = len(programs)
    f = len(times)
    pos = np.zeros((f, n, 3), dtype=np.float64)
    vel = np.zeros((f, n, 3), dtype=np.float64)
    acc = np.zeros((f, n, 3), dtype=np.float64)
    col = np.ones((f, n, 3), dtype=np.float64)
    bri = np.ones((f, n), dtype=np.float64)
    roles = np.zeros((f, n), dtype=np.int8)

    for i, program in enumerate(programs):
        p, v, a = _sample_trajectory(program, times)
        c, b = _sample_lighting(program, times)
        pos[:, i, :] = p
        vel[:, i, :] = v
        acc[:, i, :] = a
        col[:, i, :] = c
        bri[:, i] = b
        roles[:, i] = _sample_roles(program, times)

    return SampledShow(
        times=times,
        positions=pos,
        velocities=vel,
        accelerations=acc,
        colors=col,
        brightness=bri,
        roles=roles,
        droneIds=[p.droneId for p in programs],
    )


def time_grid(start: float, end: float, hz: float) -> np.ndarray:
    frames = max(2, int((end - start) * hz) + 1)
    return np.linspace(start, end, frames)


def show_view_mask(brightness: np.ndarray, threshold: float = VISUAL_THRESHOLD) -> np.ndarray:
    """Show view: what the audience sees. Never used by safety."""
    return brightness > threshold


def engineering_classes(roles: np.ndarray, brightness: np.ndarray, threshold: float = VISUAL_THRESHOLD) -> np.ndarray:
    """Engineering view: every physical drone, colour-coded by what it is doing."""
    out = np.full(roles.shape, CLASS_RESERVE, dtype=np.int8)
    visible = brightness > threshold
    out[roles == ROLE_CODES["FORMATION"]] = CLASS_VISIBLE
    out[roles == ROLE_CODES["TAKEOFF"]] = CLASS_VISIBLE
    out[roles == ROLE_CODES["RTH"]] = CLASS_VISIBLE
    out[roles == ROLE_CODES["EFFECT"]] = CLASS_EFFECT
    out[roles == ROLE_CODES["STAGING"]] = CLASS_DARK_STAGING
    out[(roles == ROLE_CODES["FORMATION"]) & ~visible] = CLASS_DARK_STAGING
    return out
