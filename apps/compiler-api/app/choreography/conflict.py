"""Conflict detection across compiled programs.

Dark drones are ordinary aircraft here. Nothing in this module reads
brightness.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from app.choreography.sampling import CODE_ROLES, SampledShow, sample_programs, time_grid
from app.choreography.tracks import DroneProgram
from app.models import DroneProfile, SafetyProfile
from app.safety.geometry import closing_speeds, swept_distances

Vec3 = tuple[float, float, float]


class Conflict(BaseModel):
    droneA: int
    droneB: int
    timeOfClosestApproach: float
    minimumDistance: float
    requiredDistance: float
    relativeVelocity: float
    severity: Literal["warn", "error"]
    contextA: str = ""
    contextB: str = ""
    positions: list[Vec3] = Field(default_factory=list)

    @property
    def key(self) -> tuple[int, int]:
        return (min(self.droneA, self.droneB), max(self.droneA, self.droneB))

    @property
    def deficit(self) -> float:
        return self.requiredDistance - self.minimumDistance


class ConflictGraph(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)
    sampledFrames: int = 0
    checkedPairs: int = 0
    minimumSeparation: float = 0.0
    # The requirement in force at the closest approach, not the show's worst.
    requiredSeparation: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(c.severity == "error" for c in self.conflicts)

    def nodes(self) -> set[int]:
        out: set[int] = set()
        for c in self.conflicts:
            out.add(c.droneA)
            out.add(c.droneB)
        return out

    def neighbors(self, drone: int) -> set[int]:
        out: set[int] = set()
        for c in self.conflicts:
            if c.droneA == drone:
                out.add(c.droneB)
            elif c.droneB == drone:
                out.add(c.droneA)
        return out

    def errors(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.severity == "error"]

    def worst(self) -> Conflict | None:
        errs = self.errors() or self.conflicts
        return max(errs, key=lambda c: c.deficit) if errs else None

    def involving(self, drones: set[int]) -> list[Conflict]:
        return [c for c in self.conflicts if c.droneA in drones or c.droneB in drones]


def static_separation(profile: DroneProfile, safety: SafetyProfile, phase: str = "show") -> float:
    base = (
        profile.minimumSeparationM
        + profile.radiusM * 2
        + safety.navigationUncertaintyM
        + safety.windAllowanceM
        + safety.operatorMarginM
    )
    if phase in {"takeoff", "landing"}:
        base = max(base, safety.takeoffSeparationM)
    return base


def detect_conflicts(
    programs: list[DroneProgram],
    profile: DroneProfile,
    safety: SafetyProfile,
    *,
    start: float = 0.0,
    end: float | None = None,
    hz: float = 8.0,
    limit: int = 240,
    sampled: SampledShow | None = None,
) -> ConflictGraph:
    if not programs:
        return ConflictGraph()

    if end is None:
        end = max((p.trajectoryTrack.endTime for p in programs), default=0.0)
    if end <= start:
        return ConflictGraph()

    if sampled is None:
        sampled = sample_programs(programs, time_grid(start, end, hz))

    static = static_separation(profile, safety)
    vfactor = safety.velocitySeparationFactor
    search_r = max(static * 2.2, 5.0)

    worst: dict[tuple[int, int], Conflict] = {}
    checked = 0
    min_sep = math.inf
    worst_req = static
    ids = sampled.droneIds
    times = sampled.times

    for fi in range(sampled.frames):
        frame = sampled.positions[fi]
        pairs = np.array(list(cKDTree(frame).query_pairs(search_r)), dtype=np.intp)
        if len(pairs) == 0:
            continue
        ia, ja = pairs[:, 0], pairs[:, 1]
        checked += len(ia)
        d_now = np.linalg.norm(frame[ia] - frame[ja], axis=1)
        vel = sampled.velocities[fi]
        close = closing_speeds(frame[ia], frame[ja], vel[ia], vel[ja])
        if fi + 1 < sampled.frames:
            nxt = sampled.positions[fi + 1]
            d_seg, u_seg = swept_distances(frame[ia], nxt[ia], frame[ja], nxt[ja])
            measured = np.minimum(d_now, d_seg)
        else:
            u_seg = np.zeros(len(ia))
            measured = d_now
        req = static + np.maximum(close, 0.0) * vfactor
        # Pair the reported minimum with the requirement that applied at that
        # moment. Quoting the global worst requirement next to the global
        # minimum compares two unrelated instants and reads as a violation
        # even when every pair in the show was comfortably legal.
        tightest = int(measured.argmin())
        if float(measured[tightest]) < min_sep:
            min_sep = float(measured[tightest])
            worst_req = float(req[tightest])

        flagged = np.nonzero(measured < req * 1.15)[0]
        dt = times[min(fi + 1, len(times) - 1)] - times[fi]
        for k in flagged:
            i, j = int(ia[k]), int(ja[k])
            a, b = ids[i], ids[j]
            key = (min(a, b), max(a, b))
            severity: Literal["warn", "error"] = "error" if measured[k] < req[k] else "warn"
            prior = worst.get(key)
            if prior is not None and prior.minimumDistance <= float(measured[k]):
                continue
            when = float(times[fi] + float(u_seg[k]) * dt)
            worst[key] = Conflict(
                droneA=a,
                droneB=b,
                timeOfClosestApproach=round(when, 4),
                minimumDistance=round(float(measured[k]), 4),
                requiredDistance=round(float(req[k]), 4),
                relativeVelocity=round(float(close[k]), 4),
                severity=severity,
                contextA=CODE_ROLES.get(int(sampled.roles[fi, i]), "RESERVE"),
                contextB=CODE_ROLES.get(int(sampled.roles[fi, j]), "RESERVE"),
                positions=[tuple(frame[i]), tuple(frame[j])],  # type: ignore[list-item]
            )

    conflicts = sorted(worst.values(), key=lambda c: (-c.deficit, c.key))[:limit]
    return ConflictGraph(
        conflicts=conflicts,
        sampledFrames=sampled.frames,
        checkedPairs=checked,
        minimumSeparation=round(min_sep if math.isfinite(min_sep) else static, 4),
        requiredSeparation=round(worst_req, 4),
    )
