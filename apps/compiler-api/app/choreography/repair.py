"""Local conflict repair.

Strategies are attempted in a fixed order and every applied change is
recorded. Trajectories are never modified silently.
"""

from __future__ import annotations

import math
from typing import Callable, Literal

from pydantic import BaseModel, Field

from app.choreography.conflict import Conflict, ConflictGraph, static_separation
from app.choreography.tracks import DroneProgram, MotionStyle
from app.models import DroneProfile, SafetyProfile
from app.trajectory.minjerk import min_duration

Vec3 = tuple[float, float, float]

RepairStrategy = Literal[
    "destination-reassignment",
    "staging-start-adjustment",
    "temporal-offset",
    "alternate-staging-position",
    "intermediate-waypoint",
    "vertical-detour",
    "extend-duration",
]

STRATEGY_ORDER: tuple[RepairStrategy, ...] = (
    "destination-reassignment",
    "staging-start-adjustment",
    "temporal-offset",
    "alternate-staging-position",
    "intermediate-waypoint",
    "vertical-detour",
    "extend-duration",
)


class StagedMotion(BaseModel):
    """Mutable description of one drone's dark repositioning.

    A staged drone flies twice: out to the effect and home again. Both legs
    are described here so a repair can act on whichever one is actually in
    conflict.
    """

    droneId: int
    groupId: str
    targetIndex: int
    windowStart: float
    startTime: float
    arrivalTime: float
    holdUntil: float
    fromPosition: Vec3
    toPosition: Vec3
    waypoints: list[Vec3] = Field(default_factory=list)
    # The planner's corridor is flown as one curve. A repair that reroutes
    # this drone takes it off the group's shared schedule, so the curve loses
    # its separation argument and the motion falls back to discrete legs.
    style: MotionStyle = "minjerk"
    floorZ: float = 1.0
    blackoutStart: float | None = None

    # The flight home. `returnStart` is the group's shared departure; the
    # repair pass slips an individual drone with `timeOffset` so the
    # synchronised plan stays inspectable underneath.
    returnStart: float = 0.0
    returnFrom: Vec3 = (0.0, 0.0, 0.0)
    returnTo: Vec3 = (0.0, 0.0, 0.0)
    returnWaypoints: list[Vec3] = Field(default_factory=list)
    timeOffset: float = 0.0

    def travel_distance(self) -> float:
        pts = [self.fromPosition, *self.waypoints, self.toPosition]
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))


class MotionLeg:
    """Read/write view of whichever leg a conflict falls on.

    The seven repair strategies are the same either way — reassign the
    destination, leave earlier, slip in time, park elsewhere, route around,
    go over, take longer. Without this view they could only ever be applied
    to the outbound flight, which leaves every conflict on the way home with
    nothing to try.
    """

    def __init__(self, motion: StagedMotion, outbound: bool) -> None:
        self.motion = motion
        self.outbound = outbound

    @property
    def phase(self) -> str:
        return "outbound" if self.outbound else "return"

    @property
    def floor(self) -> float:
        return self.motion.floorZ

    @property
    def earliest(self) -> float:
        return self.motion.windowStart if self.outbound else self.motion.returnStart

    @property
    def start(self) -> float:
        m = self.motion
        return m.startTime if self.outbound else m.returnStart + m.timeOffset

    @start.setter
    def start(self, value: float) -> None:
        if self.outbound:
            self.motion.startTime = value
        else:
            self.motion.timeOffset = value - self.motion.returnStart

    @property
    def arrival(self) -> float:
        return self.motion.arrivalTime if self.outbound else self.motion.holdUntil

    @property
    def origin(self) -> Vec3:
        return self.motion.fromPosition if self.outbound else self.motion.returnFrom

    @property
    def destination(self) -> Vec3:
        return self.motion.toPosition if self.outbound else self.motion.returnTo

    @destination.setter
    def destination(self, value: Vec3) -> None:
        if self.outbound:
            self.motion.toPosition = value
        else:
            self.motion.returnTo = value

    @property
    def waypoints(self) -> list[Vec3]:
        return self.motion.waypoints if self.outbound else self.motion.returnWaypoints

    @waypoints.setter
    def waypoints(self, value: list[Vec3]) -> None:
        if self.outbound:
            self.motion.waypoints = value
            self.motion.style = "minjerk"
        else:
            self.motion.returnWaypoints = value


class RepairRecord(BaseModel):
    droneA: int
    droneB: int
    strategy: RepairStrategy | Literal["none"]
    applied: bool
    reason: str
    separationBefore: float
    separationAfter: float
    requiredSeparation: float
    timeOfClosestApproach: float


class RepairReport(BaseModel):
    records: list[RepairRecord] = Field(default_factory=list)
    attempted: int = 0
    resolved: int = 0
    unresolved: int = 0

    @property
    def applied_records(self) -> list[RepairRecord]:
        return [r for r in self.records if r.applied]


RebuildFn = Callable[[StagedMotion], None]


def pair_min_distance(
    a: DroneProgram,
    b: DroneProgram,
    t0: float,
    t1: float,
    samples: int = 36,
) -> tuple[float, float]:
    best = math.inf
    when = t0
    for k in range(samples + 1):
        t = t0 + (t1 - t0) * (k / samples)
        d = math.dist(a.position(t), b.position(t))
        if d < best:
            best = d
            when = t
    return best, when


class ConflictRepairer:
    def __init__(
        self,
        programs: dict[int, DroneProgram],
        motions: dict[int, StagedMotion],
        rebuild: RebuildFn,
        profile: DroneProfile,
        safety: SafetyProfile,
    ) -> None:
        self.programs = programs
        self.motions = motions
        self.rebuild = rebuild
        self.profile = profile
        self.safety = safety
        self.required = static_separation(profile, safety)

    # --- helpers ----------------------------------------------------------

    def _window(self, conflict: Conflict) -> tuple[float, float]:
        t = conflict.timeOfClosestApproach
        spans = [
            (m.startTime, m.holdUntil)
            for m in (self.motions.get(conflict.droneA), self.motions.get(conflict.droneB))
            if m is not None
        ]
        lo = min([s for s, _ in spans], default=t - 2.0)
        hi = max([e for _, e in spans], default=t + 2.0)
        return min(lo, t - 1.0), max(hi, t + 1.0)

    def _separation(self, conflict: Conflict) -> tuple[float, float]:
        a = self.programs.get(conflict.droneA)
        b = self.programs.get(conflict.droneB)
        if a is None or b is None:
            return math.inf, conflict.timeOfClosestApproach
        t0, t1 = self._window(conflict)
        return pair_min_distance(a, b, t0, t1)

    def _neighbors_ok(self, conflict: Conflict, touched: list[int], graph: ConflictGraph) -> bool:
        """Cheap guard so a repair does not trade one conflict for another."""
        t0, t1 = self._window(conflict)
        watch: set[int] = set()
        for d in touched:
            watch |= graph.neighbors(d)
            motion = self.motions.get(d)
            if motion:
                watch |= {m.droneId for m in self.motions.values() if m.groupId == motion.groupId}
        watch -= set(touched)
        for d in touched:
            a = self.programs.get(d)
            if a is None:
                continue
            for other in sorted(watch):
                b = self.programs.get(other)
                if b is None:
                    continue
                sep, _ = pair_min_distance(a, b, t0, t1, samples=20)
                if sep < self.required:
                    return False
        return True

    def _feasible(self, leg: MotionLeg) -> bool:
        duration = leg.arrival - leg.start
        if duration <= 1e-3:
            return False
        points = [leg.origin, *leg.waypoints, leg.destination]
        need = sum(
            min_duration(
                math.dist(p, q),
                self.profile.maxHorizontalSpeedMps,
                self.profile.maxAccelerationMps2,
            )
            for p, q in zip(points, points[1:], strict=False)
        )
        return need <= duration + 1e-6

    def _leg(self, motion: StagedMotion, when: float) -> MotionLeg:
        """Which flight the conflict happens on."""
        outbound = when <= motion.arrivalTime + 1e-6 or motion.returnStart <= 0.0
        return MotionLeg(motion, outbound)

    # --- strategies -------------------------------------------------------

    def _try(
        self,
        conflict: Conflict,
        strategy: RepairStrategy,
        graph: ConflictGraph,
    ) -> tuple[bool, str, float]:
        when = conflict.timeOfClosestApproach
        ma = self.motions.get(conflict.droneA)
        mb = self.motions.get(conflict.droneB)
        candidates = [m for m in (ma, mb) if m is not None]
        if not candidates:
            return False, "neither drone is dark-staging; visible motion is not silently retimed", math.inf

        legs = [self._leg(m, when) for m in candidates]
        snapshot = {m.droneId: m.model_copy(deep=True) for m in candidates}

        def restore() -> None:
            for did, saved in snapshot.items():
                self.motions[did] = saved
                self.rebuild(saved)

        detail = ""
        phase = legs[0].phase
        # On the way home a drone is flying to an assigned formation point, not
        # to a parking spot. Moving that point would leave a hole in the eagle,
        # and swapping two of them would strand both drones when the formation
        # they were routed to next is already compiled. Those two strategies
        # only apply outbound.
        if not legs[0].outbound and strategy in {
            "destination-reassignment",
            "alternate-staging-position",
        }:
            return False, f"{strategy} would move a compiled formation point", math.inf

        if strategy == "destination-reassignment":
            if len(legs) < 2 or ma is None or mb is None or ma.groupId != mb.groupId:
                return False, "no sibling destination to swap", math.inf
            la, lb = legs
            if la.phase != lb.phase:
                return False, "the two drones are on different legs", math.inf
            la.destination, lb.destination = lb.destination, la.destination
            la.waypoints, lb.waypoints = [], []
            ma.targetIndex, mb.targetIndex = mb.targetIndex, ma.targetIndex
            detail = f"swapped {phase} destinations for D{ma.droneId} and D{mb.droneId}"
            self.rebuild(ma)
            self.rebuild(mb)

        elif strategy == "staging-start-adjustment":
            leg = max(legs, key=lambda x: x.start)
            if leg.start <= leg.earliest + 1e-3:
                return False, f"{leg.phase} leg already starts at its window floor", math.inf
            leg.start = leg.earliest
            detail = f"D{leg.motion.droneId} {leg.phase} starts at {leg.start:.2f}s"
            self.rebuild(leg.motion)

        elif strategy == "temporal-offset":
            leg = min(legs, key=lambda x: x.start)
            shift = 0.35
            if leg.start + shift >= leg.arrival - 0.2:
                return False, "no room for a temporal offset", math.inf
            leg.start = leg.start + shift
            if not self._feasible(leg):
                restore()
                return False, "temporal offset would exceed the flight envelope", math.inf
            detail = f"D{leg.motion.droneId} {leg.phase} delayed {shift:.2f}s"
            self.rebuild(leg.motion)

        elif strategy == "alternate-staging-position":
            leg = legs[0]
            offset = self.required * 1.2
            lateral = _lateral(leg.origin, leg.destination)
            leg.destination = (
                leg.destination[0] + lateral[0] * offset,
                leg.destination[1] + lateral[1] * offset,
                max(leg.destination[2] + lateral[2] * offset, leg.floor),
            )
            detail = f"D{leg.motion.droneId} arrives {offset:.2f} m off the nominal {leg.phase} point"
            self.rebuild(leg.motion)

        elif strategy == "intermediate-waypoint":
            leg = legs[0]
            mid = _midpoint(leg.origin, leg.destination)
            lateral = _lateral(leg.origin, leg.destination)
            offset = self.required * 1.5
            leg.waypoints = [
                (
                    mid[0] + lateral[0] * offset,
                    mid[1] + lateral[1] * offset,
                    max(mid[2] + lateral[2] * offset, leg.floor),
                )
            ]
            if not self._feasible(leg):
                restore()
                return False, "waypoint detour does not fit the window", math.inf
            detail = f"D{leg.motion.droneId} routed via a {offset:.2f} m lateral waypoint"
            self.rebuild(leg.motion)

        elif strategy == "vertical-detour":
            leg = legs[0]
            mid = _midpoint(leg.origin, leg.destination)
            lift = self.required * 1.4
            leg.waypoints = [(mid[0], mid[1], max(mid[2] + lift, leg.floor))]
            if not self._feasible(leg):
                restore()
                return False, "vertical detour does not fit the window", math.inf
            detail = f"D{leg.motion.droneId} lifted {lift:.2f} m over the crossing"
            self.rebuild(leg.motion)

        elif strategy == "extend-duration":
            leg = max(legs, key=lambda x: x.start)
            target = leg.motion
            if not leg.outbound:
                return False, "the flight home cannot start before the effect ends", math.inf
            extra = 1.5
            new_start = max(0.0, target.windowStart - extra)
            if new_start >= target.startTime - 1e-3:
                return False, "no earlier blackout available", math.inf
            target.windowStart = new_start
            target.startTime = new_start
            target.blackoutStart = new_start
            detail = f"D{target.droneId} blackout extended to {new_start:.2f}s for a longer approach"
            self.rebuild(target)

        else:
            return False, "unknown strategy", math.inf

        sep, _ = self._separation(conflict)
        touched = [m.droneId for m in candidates]
        if sep >= self.required and self._neighbors_ok(conflict, touched, graph):
            return True, detail, sep
        restore()
        return False, f"{detail or strategy} did not clear the conflict", sep

    # --- entry point ------------------------------------------------------

    def repair(self, graph: ConflictGraph, max_conflicts: int = 40) -> RepairReport:
        report = RepairReport()
        for conflict in graph.errors()[:max_conflicts]:
            report.attempted += 1
            before, when = self._separation(conflict)
            if before >= self.required:
                report.records.append(
                    RepairRecord(
                        droneA=conflict.droneA,
                        droneB=conflict.droneB,
                        strategy="none",
                        applied=False,
                        reason="already clear after an earlier repair",
                        separationBefore=round(before, 4),
                        separationAfter=round(before, 4),
                        requiredSeparation=round(self.required, 4),
                        timeOfClosestApproach=round(when, 4),
                    )
                )
                report.resolved += 1
                continue

            resolved = False
            last_reason = "no strategy applied"
            last_sep = before
            for strategy in STRATEGY_ORDER:
                ok, reason, sep = self._try(conflict, strategy, graph)
                if ok:
                    report.records.append(
                        RepairRecord(
                            droneA=conflict.droneA,
                            droneB=conflict.droneB,
                            strategy=strategy,
                            applied=True,
                            reason=reason,
                            separationBefore=round(before, 4),
                            separationAfter=round(sep, 4),
                            requiredSeparation=round(self.required, 4),
                            timeOfClosestApproach=round(when, 4),
                        )
                    )
                    report.resolved += 1
                    resolved = True
                    break
                last_reason = reason
                if math.isfinite(sep):
                    last_sep = sep

            if not resolved:
                report.records.append(
                    RepairRecord(
                        droneA=conflict.droneA,
                        droneB=conflict.droneB,
                        strategy="none",
                        applied=False,
                        reason=last_reason,
                        separationBefore=round(before, 4),
                        separationAfter=round(last_sep, 4),
                        requiredSeparation=round(self.required, 4),
                        timeOfClosestApproach=round(when, 4),
                    )
                )
                report.unresolved += 1
        return report


def _midpoint(a: Vec3, b: Vec3) -> Vec3:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def _lateral(a: Vec3, b: Vec3) -> Vec3:
    """Unit vector perpendicular to travel, biased horizontal."""
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1e-6:
        return (1.0, 0.0, 0.0)
    dx, dy, dz = dx / n, dy / n, dz / n
    lx, ly, lz = -dy, dx, 0.0
    ln = math.hypot(lx, ly)
    if ln < 1e-6:
        return (1.0, 0.0, 0.0)
    return (lx / ln, ly / ln, lz)
