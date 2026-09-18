"""Independent time-varying tracks for a logical drone.

Physical motion, visual appearance and temporal role are three separate
functions of show time. The canonical representation is continuous and
semantic; sampling happens only for rendering, validation and export.
"""

from __future__ import annotations

import bisect
import math
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr

Vec3 = tuple[float, float, float]
Rgb = tuple[float, float, float]

VISUAL_THRESHOLD = 0.02

RoleType = Literal["FORMATION", "EFFECT", "STAGING", "RESERVE", "TAKEOFF", "RTH"]
Interpolation = Literal["step", "linear"]
MotionStyle = Literal["hold", "minjerk", "linear", "spline"]


def _minjerk_s(u: float) -> float:
    return u * u * u * (10.0 + u * (-15.0 + 6.0 * u))


def _minjerk_ds(u: float) -> float:
    return u * u * (30.0 + u * (-60.0 + 30.0 * u))


def _minjerk_dds(u: float) -> float:
    return u * (60.0 + u * (-180.0 + 120.0 * u))


# ---------------------------------------------------------------- trajectory


class TrajectorySegment(BaseModel):
    """Analytic motion primitive. Not a bag of samples."""

    startTime: float
    duration: float
    start: Vec3
    end: Vec3
    style: MotionStyle = "minjerk"
    floorZ: float = 0.0
    sourceId: str = ""
    # Interior knots for `spline`. A sampled path flown as a chain of
    # rest-to-rest hops brakes to a standstill at every sample, which costs far
    # more acceleration than the path itself demands; one spline through the
    # same knots asks the aircraft for the motion that was actually authored.
    waypoints: list[Vec3] = Field(default_factory=list)

    _moments: list[Vec3] | None = PrivateAttr(default=None)

    @property
    def endTime(self) -> float:
        return self.startTime + self.duration

    def _u(self, t: float) -> float:
        if self.duration <= 1e-9:
            return 1.0
        return min(1.0, max(0.0, (t - self.startTime) / self.duration))

    def _knots(self) -> list[Vec3]:
        return [self.start, *self.waypoints, self.end]

    def _curvature(self) -> list[Vec3]:
        """Natural-cubic second derivatives at the knots, cached.

        Natural rather than Catmull-Rom because acceleration has to be
        continuous. A Catmull-Rom curve only matches tangents, so acceleration
        jumps at every knot, and a jump in acceleration is unbounded jerk: on
        a 13-second plume sampled at 8 Hz it read as 10 m/s³ against a 6 m/s³
        limit. The natural boundary condition also pins acceleration to zero
        at both ends, which is what lets this segment sit between two
        rest-to-rest min-jerk flights without a discontinuity at the seams.
        """
        if self._moments is not None:
            return self._moments
        knots = self._knots()
        n = len(knots) - 1
        m: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(n + 1)]
        if n >= 2:
            h = 1.0 / n
            for d in range(3):
                # Thomas algorithm on the tridiagonal (1, 4, 1) system.
                rhs = [
                    6.0 * (knots[i - 1][d] - 2.0 * knots[i][d] + knots[i + 1][d]) / (h * h)
                    for i in range(1, n)
                ]
                c = [0.0] * (n - 1)
                r = [0.0] * (n - 1)
                beta = 4.0
                c[0] = 1.0 / beta
                r[0] = rhs[0] / beta
                for i in range(1, n - 1):
                    beta = 4.0 - c[i - 1]
                    c[i] = 1.0 / beta
                    r[i] = (rhs[i] - r[i - 1]) / beta
                for i in range(n - 2, -1, -1):
                    r[i] = r[i] - c[i] * (r[i + 1] if i + 1 < n - 1 else 0.0)
                for i in range(1, n):
                    m[i][d] = r[i - 1]
        self._moments = [(row[0], row[1], row[2]) for row in m]
        return self._moments

    def _span(self, u: float) -> tuple[list[Vec3], list[Vec3], int, float, int]:
        knots = self._knots()
        n = len(knots) - 1
        x = min(max(u, 0.0), 1.0) * n
        i = min(int(x), n - 1)
        return knots, self._curvature(), i, x - i, n

    def position(self, t: float) -> Vec3:
        u = self._u(t)
        if self.style == "spline" and self.waypoints:
            knots, mom, i, w, n = self._span(u)
            h2 = (1.0 / n) ** 2
            a, b = 1.0 - w, w
            out = tuple(
                mom[i][d] * h2 * a * a * a / 6.0
                + mom[i + 1][d] * h2 * b * b * b / 6.0
                + (knots[i][d] - mom[i][d] * h2 / 6.0) * a
                + (knots[i + 1][d] - mom[i + 1][d] * h2 / 6.0) * b
                for d in range(3)
            )
            return (out[0], out[1], max(out[2], self.floorZ))
        if self.style == "hold":
            s = 0.0
        elif self.style == "linear":
            s = u
        else:
            s = _minjerk_s(u)
        x = self.start[0] + s * (self.end[0] - self.start[0])
        y = self.start[1] + s * (self.end[1] - self.start[1])
        z = self.start[2] + s * (self.end[2] - self.start[2])
        return (x, y, max(z, self.floorZ))

    def velocity(self, t: float) -> Vec3:
        if self.style == "hold" or self.duration <= 1e-9:
            return (0.0, 0.0, 0.0)
        u = self._u(t)
        if self.style == "spline" and self.waypoints:
            knots, mom, i, w, n = self._span(u)
            h = 1.0 / n
            a, b = 1.0 - w, w
            k = 1.0 / self.duration
            out = tuple(
                (
                    -mom[i][d] * h * a * a / 2.0
                    + mom[i + 1][d] * h * b * b / 2.0
                    + (knots[i + 1][d] - knots[i][d]) / h
                    - (mom[i + 1][d] - mom[i][d]) * h / 6.0
                )
                * k
                for d in range(3)
            )
            return (out[0], out[1], out[2])
        ds = 1.0 if self.style == "linear" else _minjerk_ds(u)
        k = ds / self.duration
        return (
            (self.end[0] - self.start[0]) * k,
            (self.end[1] - self.start[1]) * k,
            (self.end[2] - self.start[2]) * k,
        )

    def acceleration(self, t: float) -> Vec3:
        if self.duration <= 1e-9:
            return (0.0, 0.0, 0.0)
        u = self._u(t)
        if self.style == "spline" and self.waypoints:
            _knots, mom, i, w, n = self._span(u)
            k = 1.0 / (self.duration * self.duration)
            out = tuple(
                (mom[i][d] * (1.0 - w) + mom[i + 1][d] * w) * k for d in range(3)
            )
            return (out[0], out[1], out[2])
        if self.style != "minjerk":
            return (0.0, 0.0, 0.0)
        k = _minjerk_dds(u) / (self.duration * self.duration)
        return (
            (self.end[0] - self.start[0]) * k,
            (self.end[1] - self.start[1]) * k,
            (self.end[2] - self.start[2]) * k,
        )

    def length(self) -> float:
        if self.style == "spline" and self.waypoints:
            knots = self._knots()
            return sum(math.dist(a, b) for a, b in zip(knots, knots[1:], strict=False))
        return math.dist(self.start, self.end)


class TrajectoryTrack(BaseModel):
    segments: list[TrajectorySegment] = Field(default_factory=list)

    def sorted_segments(self) -> list[TrajectorySegment]:
        return sorted(self.segments, key=lambda s: s.startTime)

    def normalize(self) -> "TrajectoryTrack":
        self.segments = self.sorted_segments()
        return self

    def _pick(self, t: float) -> TrajectorySegment | None:
        segs = self.segments
        if not segs:
            return None
        starts = [s.startTime for s in segs]
        i = bisect.bisect_right(starts, t) - 1
        if i < 0:
            return segs[0]
        return segs[i]

    def position(self, t: float) -> Vec3:
        seg = self._pick(t)
        if seg is None:
            return (0.0, 0.0, 0.0)
        return seg.position(t)

    def velocity(self, t: float) -> Vec3:
        seg = self._pick(t)
        if seg is None or t < seg.startTime or t > seg.endTime:
            return (0.0, 0.0, 0.0)
        return seg.velocity(t)

    def acceleration(self, t: float) -> Vec3:
        seg = self._pick(t)
        if seg is None or t < seg.startTime or t > seg.endTime:
            return (0.0, 0.0, 0.0)
        return seg.acceleration(t)

    def speed(self, t: float) -> float:
        v = self.velocity(t)
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    @property
    def endTime(self) -> float:
        return max((s.endTime for s in self.segments), default=0.0)

    def replace_window(self, start: float, end: float, replacement: list[TrajectorySegment]) -> None:
        """Splice new motion into [start, end], trimming whatever was there."""
        kept: list[TrajectorySegment] = []
        for seg in self.sorted_segments():
            if seg.endTime <= start + 1e-9 or seg.startTime >= end - 1e-9:
                kept.append(seg)
                continue
            if seg.startTime < start - 1e-9:
                head_end = seg.position(start)
                kept.append(
                    seg.model_copy(update={"duration": start - seg.startTime, "end": head_end})
                )
            if seg.endTime > end + 1e-9:
                tail_start = seg.position(end)
                kept.append(
                    seg.model_copy(
                        update={"startTime": end, "duration": seg.endTime - end, "start": tail_start}
                    )
                )
        self.segments = sorted([*kept, *replacement], key=lambda s: s.startTime)


# ------------------------------------------------------------------ lighting


class LightingKeyframe(BaseModel):
    time: float
    rgbLinear: Rgb = (1.0, 1.0, 1.0)
    brightness: float = 1.0
    interpolation: Interpolation = "linear"


class LightingTrack(BaseModel):
    """Continuous colour + brightness. Brightness is never a boolean."""

    keyframes: list[LightingKeyframe] = Field(default_factory=list)

    def normalize(self) -> "LightingTrack":
        self.keyframes = sorted(self.keyframes, key=lambda k: k.time)
        return self

    def _bracket(self, t: float) -> tuple[LightingKeyframe, LightingKeyframe, float]:
        keys = self.keyframes
        times = [k.time for k in keys]
        i = bisect.bisect_right(times, t) - 1
        if i < 0:
            return keys[0], keys[0], 0.0
        if i >= len(keys) - 1:
            return keys[-1], keys[-1], 0.0
        a, b = keys[i], keys[i + 1]
        if a.interpolation == "step":
            return a, a, 0.0
        span = b.time - a.time
        u = 0.0 if span <= 1e-9 else (t - a.time) / span
        return a, b, min(1.0, max(0.0, u))

    def brightness(self, t: float) -> float:
        if not self.keyframes:
            return 1.0
        a, b, u = self._bracket(t)
        return min(1.0, max(0.0, a.brightness + u * (b.brightness - a.brightness)))

    def color(self, t: float) -> Rgb:
        if not self.keyframes:
            return (1.0, 1.0, 1.0)
        a, b, u = self._bracket(t)
        return (
            a.rgbLinear[0] + u * (b.rgbLinear[0] - a.rgbLinear[0]),
            a.rgbLinear[1] + u * (b.rgbLinear[1] - a.rgbLinear[1]),
            a.rgbLinear[2] + u * (b.rgbLinear[2] - a.rgbLinear[2]),
        )

    def is_visually_active(self, t: float, threshold: float = VISUAL_THRESHOLD) -> bool:
        """Derived, never stored. Safety code must not call this."""
        return self.brightness(t) > threshold

    def dark_windows(self, start: float, end: float, threshold: float = VISUAL_THRESHOLD, step: float = 0.1) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        t = start
        open_at: float | None = None
        while t <= end + 1e-9:
            dark = self.brightness(t) <= threshold
            if dark and open_at is None:
                open_at = t
            elif not dark and open_at is not None:
                out.append((open_at, t))
                open_at = None
            t += step
        if open_at is not None:
            out.append((open_at, end))
        return out

    def replace_window(self, start: float, end: float, replacement: list[LightingKeyframe]) -> None:
        kept = [k for k in self.keyframes if k.time < start - 1e-9 or k.time > end + 1e-9]
        self.keyframes = sorted([*kept, *replacement], key=lambda k: k.time)


# ---------------------------------------------------------------------- role


class RoleSegment(BaseModel):
    startTime: float
    endTime: float
    roleType: RoleType = "FORMATION"
    roleId: str = ""
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)


class RoleTrack(BaseModel):
    segments: list[RoleSegment] = Field(default_factory=list)

    def normalize(self) -> "RoleTrack":
        self.segments = sorted(self.segments, key=lambda s: s.startTime)
        return self

    def at(self, t: float) -> RoleSegment | None:
        best: RoleSegment | None = None
        for seg in self.segments:
            if seg.startTime - 1e-9 <= t < seg.endTime + 1e-9:
                best = seg
        return best

    def role_type(self, t: float) -> RoleType:
        seg = self.at(t)
        return seg.roleType if seg else "RESERVE"

    def role_id(self, t: float) -> str:
        seg = self.at(t)
        return seg.roleId if seg else ""

    def replace_window(self, start: float, end: float, replacement: list[RoleSegment]) -> None:
        kept: list[RoleSegment] = []
        for seg in self.segments:
            if seg.endTime <= start + 1e-9 or seg.startTime >= end - 1e-9:
                kept.append(seg)
                continue
            if seg.startTime < start - 1e-9:
                kept.append(seg.model_copy(update={"endTime": start}))
            if seg.endTime > end + 1e-9:
                kept.append(seg.model_copy(update={"startTime": end}))
        self.segments = sorted([*kept, *replacement], key=lambda s: s.startTime)


# ------------------------------------------------------------------- program


class DroneProgram(BaseModel):
    """One logical drone across the whole show."""

    droneId: int
    trajectoryTrack: TrajectoryTrack = Field(default_factory=TrajectoryTrack)
    lightingTrack: LightingTrack = Field(default_factory=LightingTrack)
    roleTrack: RoleTrack = Field(default_factory=RoleTrack)

    def position(self, t: float) -> Vec3:
        return self.trajectoryTrack.position(t)

    def velocity(self, t: float) -> Vec3:
        return self.trajectoryTrack.velocity(t)

    def acceleration(self, t: float) -> Vec3:
        return self.trajectoryTrack.acceleration(t)

    def color(self, t: float) -> Rgb:
        return self.lightingTrack.color(t)

    def brightness(self, t: float) -> float:
        return self.lightingTrack.brightness(t)

    def is_visually_active(self, t: float, threshold: float = VISUAL_THRESHOLD) -> bool:
        return self.lightingTrack.is_visually_active(t, threshold)

    def role(self, t: float) -> RoleType:
        return self.roleTrack.role_type(t)

    def normalize(self) -> "DroneProgram":
        self.trajectoryTrack.normalize()
        self.lightingTrack.normalize()
        self.roleTrack.normalize()
        return self


class CompiledDroneProgram(BaseModel):
    """Self-contained onboard payload: no ground station required at runtime."""

    logicalDroneId: int
    trajectory: TrajectoryTrack
    lighting: LightingTrack
    roles: RoleTrack
    compilerVersion: str
    sourceProjectRevision: str
    seed: int
    algorithmVersion: int
    contentHash: str
    duration: float
