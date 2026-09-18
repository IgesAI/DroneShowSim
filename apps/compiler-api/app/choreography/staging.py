"""Dark staging.

Motion while brightness is near zero costs almost nothing visually. It costs
exactly the same physically: separation, velocity, acceleration, jerk and
geofence limits are untouched by lighting.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from app.choreography.allocation import AllocationCandidate
from app.choreography.tracks import MotionStyle, TrajectorySegment
from app.models import DroneProfile, SafetyProfile, required_separation
from app.trajectory.minjerk import PEAK_S1, PEAK_S2, min_duration

Vec3 = tuple[float, float, float]


def _length(path: list[Vec3]) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False))


StagingShape = Literal["BOX", "SPHERE", "PLANE_OFFSET"]
OcclusionPreference = Literal["behind", "any", "avoid"]


class StagingVolume(BaseModel):
    """A physically available region where visually inactive drones may wait."""

    id: str
    name: str = ""
    shape: StagingShape = "BOX"
    center: Vec3 = (0.0, 0.0, 30.0)
    rotationRad: Vec3 = (0.0, 0.0, 0.0)
    bounds: Vec3 = (20.0, 20.0, 20.0)
    normal: Vec3 = (0.0, 1.0, 0.0)
    capacity: int = 64
    priority: int = 0
    audienceOcclusionPreference: OcclusionPreference = "behind"

    def contains(self, p: Vec3) -> bool:
        if self.shape == "SPHERE":
            return math.dist(p, self.center) <= max(self.bounds[0], 1e-6)
        if self.shape == "PLANE_OFFSET":
            rel = (p[0] - self.center[0], p[1] - self.center[1], p[2] - self.center[2])
            return rel[0] * self.normal[0] + rel[1] * self.normal[1] + rel[2] * self.normal[2] >= 0.0
        return all(abs(p[i] - self.center[i]) <= max(self.bounds[i], 1e-6) for i in range(3))

    def clamp(self, p: Vec3) -> Vec3:
        if self.shape == "SPHERE":
            r = max(self.bounds[0], 1e-6)
            d = math.dist(p, self.center)
            if d <= r:
                return p
            k = r / d
            return tuple(self.center[i] + (p[i] - self.center[i]) * k for i in range(3))  # type: ignore[return-value]
        if self.shape == "PLANE_OFFSET":
            rel = (p[0] - self.center[0], p[1] - self.center[1], p[2] - self.center[2])
            signed = rel[0] * self.normal[0] + rel[1] * self.normal[1] + rel[2] * self.normal[2]
            if signed >= 0.0:
                return p
            return tuple(p[i] - signed * self.normal[i] for i in range(3))  # type: ignore[return-value]
        return tuple(  # type: ignore[return-value]
            min(self.center[i] + self.bounds[i], max(self.center[i] - self.bounds[i], p[i]))
            for i in range(3)
        )


class StagingWindow(BaseModel):
    droneId: int
    availableWindow: tuple[float, float]
    requiredArrivalTime: float
    requiredTravelTime: float
    recommendedStartTime: float
    travelDistanceM: float
    maximumVelocity: float
    maximumAcceleration: float
    feasible: bool = True
    reason: str = ""


class StagingAssignment(BaseModel):
    droneId: int
    targetIndex: int
    fromPosition: Vec3
    toPosition: Vec3
    startTime: float
    arrivalTime: float
    window: StagingWindow
    volumeId: str | None = None
    roleId: str = ""
    waypoints: list[Vec3] = Field(default_factory=list)
    # One curve rather than a chain of hops: stopping dead at each corner of
    # the corridor cost 5.8 m/s² against a 3.0 limit, for a route the aircraft
    # could otherwise fly without ever leaving 0.6.
    style: MotionStyle = "minjerk"

    @property
    def path(self) -> list[Vec3]:
        return [self.fromPosition, *self.waypoints, self.toPosition]


class StagingDiagnostics(BaseModel):
    label: str
    droneCount: int = 0
    stagingBeginsAt: float = 0.0
    eventBeginsAt: float = 0.0
    darkTravelDuration: float = 0.0
    maximumStagingVelocity: float = 0.0
    maximumStagingAcceleration: float = 0.0
    minimumPredictedSeparation: float = 0.0
    requiredSeparation: float = 0.0
    infeasibleDrones: list[int] = Field(default_factory=list)
    rejected: bool = False
    notes: list[str] = Field(default_factory=list)


class StagingPlan(BaseModel):
    label: str
    assignments: list[StagingAssignment] = Field(default_factory=list)
    diagnostics: StagingDiagnostics


class StagingRequest(BaseModel):
    label: str
    requiredArrivalTime: float
    earliestStart: float
    candidates: list[AllocationCandidate] = Field(default_factory=list)
    targets: list[Vec3] = Field(default_factory=list)
    earliestStartByDrone: dict[int, float] = Field(default_factory=dict)
    volumes: list[StagingVolume] = Field(default_factory=list)
    marginS: float = 0.4
    speedFactor: float = 0.55
    roleId: str = ""
    # Route the group behind the formation it is leaving, along the audience
    # normal. Drones peeling out of a held formation otherwise fly straight
    # through the drones still holding it, and a formation that is standing
    # still offers no shared time base to bound the crossing.
    # One translation for the whole group, not a per-drone projection: a
    # projection maps two drones at the same height and bearing but different
    # depths onto the same point, and the plume has plenty of those. A rigid
    # translation cannot change any separation at all.
    corridorShift: Vec3 | None = None


class DarkStagingPlanner:
    """Decides when invisible repositioning may begin — as late as possible."""

    def __init__(self, profile: DroneProfile, safety: SafetyProfile, samples: int = 24) -> None:
        self.profile = profile
        self.safety = safety
        self.samples = samples

    # --- windows ----------------------------------------------------------

    def travel_time(self, distance: float, dz: float, factor: float) -> float:
        vmax = max(self.profile.maxHorizontalSpeedMps * factor, 0.2)
        amax = max(self.profile.maxAccelerationMps2 * factor, 0.1)
        t = min_duration(distance, vmax, amax)
        if dz > 0:
            t = max(t, PEAK_S1 * dz / max(self.profile.maxAscentSpeedMps * factor, 0.1))
        elif dz < 0:
            t = max(t, PEAK_S1 * (-dz) / max(self.profile.maxDescentSpeedMps * factor, 0.1))
        return t

    def window(
        self,
        drone_id: int,
        start_pos: Vec3,
        end_pos: Vec3,
        required_arrival: float,
        earliest_start: float,
        margin: float,
        speed_factor: float,
        path_length: float | None = None,
    ) -> StagingWindow:
        distance = math.dist(start_pos, end_pos) if path_length is None else path_length
        dz = end_pos[2] - start_pos[2]
        comfortable = self.travel_time(distance, dz, speed_factor)
        hard_minimum = self.travel_time(distance, dz, 1.0)

        # Search backward from the deadline for the latest start that still works.
        recommended = required_arrival - (comfortable + margin)
        if recommended < earliest_start:
            recommended = earliest_start
        if recommended > required_arrival:
            recommended = required_arrival

        duration = max(required_arrival - recommended, 0.0)
        feasible = duration >= hard_minimum - 1e-6 and distance >= 0.0
        reason = ""
        if not feasible:
            reason = (
                f"needs {hard_minimum:.2f}s at full envelope but only {duration:.2f}s of dark window"
            )
        vmax = PEAK_S1 * distance / duration if duration > 1e-6 else 0.0
        amax = PEAK_S2 * distance / (duration * duration) if duration > 1e-6 else 0.0
        return StagingWindow(
            droneId=drone_id,
            availableWindow=(earliest_start, required_arrival),
            requiredArrivalTime=required_arrival,
            requiredTravelTime=hard_minimum,
            recommendedStartTime=recommended,
            travelDistanceM=distance,
            maximumVelocity=vmax,
            maximumAcceleration=amax,
            feasible=feasible,
            reason=reason,
        )

    # --- routing ----------------------------------------------------------

    def _route(self, start: Vec3, end: Vec3, shift: Vec3 | None, crossing_knots: int) -> list[Vec3]:
        """Withdraw behind the formation, cross, then come back forward.

        Every knot is an affine mix of this drone's own start and end plus a
        constant offset the whole group shares, and the spline that flies
        them weights the knots identically for every drone. So the gap
        between any two drones stays a convex blend of their gap at the start
        and their gap at the end — which is the quantity the squared-cost
        matching bounds. The corridor is safe for the same reason a
        synchronised formation morph is.

        The crossing is subdivided because the spline spends equal time
        between consecutive knots: without it the drones would amble through
        the 14 m withdrawal and then have to sprint 130 m across.
        """
        if shift is None:
            return [start, end]
        a = tuple(start[i] + shift[i] for i in range(3))
        b = tuple(end[i] + shift[i] for i in range(3))
        mid = [
            tuple(a[i] + (b[i] - a[i]) * (k / crossing_knots) for i in range(3))
            for k in range(1, crossing_knots)
        ]
        return [start, a, *mid, b, end]  # type: ignore[list-item]

    # --- planning ---------------------------------------------------------

    def plan(self, request: StagingRequest) -> StagingPlan:
        from app.choreography.allocation import match_to_targets

        pairs = match_to_targets(request.candidates, request.targets)
        notes: list[str] = []

        resolved: list[tuple[AllocationCandidate, int, Vec3, str | None]] = []
        for cand, target_index in pairs:
            target = request.targets[target_index]
            volume_id: str | None = None
            if request.volumes:
                volume = min(request.volumes, key=lambda v: (-v.priority, v.id))
                if not volume.contains(target):
                    target = volume.clamp(target)
                    notes.append(f"D{cand.droneId} staging target clamped into {volume.id}")
                volume_id = volume.id
            resolved.append((cand, target_index, target, volume_id))

        shift = request.corridorShift
        depth = math.dist((0.0, 0.0, 0.0), shift) if shift else 0.0
        crossing = 1
        if shift is not None:
            longest = max(
                (
                    math.dist(
                        tuple(c.position[i] + shift[i] for i in range(3)),
                        tuple(t[i] + shift[i] for i in range(3)),
                    )
                    for c, _idx, t, _vol in resolved
                ),
                default=0.0,
            )
            crossing = max(1, round(longest / max(depth, 1.0)))
            notes.append(
                f"group withdraws {depth:.1f} m behind the formation before crossing, "
                "so the dark flight happens in clear air"
            )
        routes = {
            cand.droneId: self._route(cand.position, target, shift, crossing)
            for cand, _idx, target, _vol in resolved
        }

        # The group leaves together. Letting each drone slip its own departure
        # to the last possible moment is cheaper on paper, but it destroys the
        # one property that makes a converging flow safe: with a shared time
        # base every pair travels along (1-s)u + s*v, so an optimal squared
        # matching bounds their separation for the whole crossing. Staggered
        # departures have no such bound, and measured on this show they let
        # 64 drones close to 0.73 m.
        lead = 0.0
        for cand, _idx, target, _vol in resolved:
            dz = target[2] - cand.position[2]
            lead = max(
                lead,
                self.travel_time(_length(routes[cand.droneId]), dz, request.speedFactor)
                + request.marginS,
            )
        floor = max(
            (request.earliestStartByDrone.get(c.droneId, request.earliestStart) for c, *_ in resolved),
            default=request.earliestStart,
        )
        start = max(floor, request.requiredArrivalTime - lead)
        if start > request.requiredArrivalTime - lead + 1e-6:
            notes.append(
                f"dark window is {request.requiredArrivalTime - floor:.2f}s, "
                f"comfortable travel needs {lead:.2f}s"
            )

        assignments: list[StagingAssignment] = []
        infeasible: list[int] = []
        for cand, target_index, target, volume_id in resolved:
            route = routes[cand.droneId]
            window = self.window(
                cand.droneId,
                cand.position,
                target,
                request.requiredArrivalTime,
                start,
                0.0,
                request.speedFactor,
                path_length=_length(route),
            )
            if not window.feasible:
                infeasible.append(cand.droneId)
            assignments.append(
                StagingAssignment(
                    droneId=cand.droneId,
                    targetIndex=target_index,
                    fromPosition=cand.position,
                    toPosition=target,
                    startTime=start,
                    arrivalTime=request.requiredArrivalTime,
                    window=window,
                    volumeId=volume_id,
                    roleId=request.roleId,
                    waypoints=route[1:-1],
                    style="spline" if shift is not None else "minjerk",
                )
            )

        diagnostics = self._diagnose(request, assignments, infeasible, notes)
        return StagingPlan(label=request.label, assignments=assignments, diagnostics=diagnostics)

    def required_lead(
        self,
        candidates: list[AllocationCandidate],
        targets: list[Vec3],
        margin: float,
        speed_factor: float,
        corridor_depth: float = 0.0,
    ) -> float:
        """How much dark time this group needs before it is due on station."""
        from app.choreography.allocation import match_to_targets

        lead = 0.0
        for cand, index in match_to_targets(candidates, targets):
            target = targets[index]
            lead = max(
                lead,
                self.travel_time(
                    math.dist(cand.position, target) + 2.0 * corridor_depth,
                    target[2] - cand.position[2],
                    speed_factor,
                )
                + margin,
            )
        return lead

    def _diagnose(
        self,
        request: StagingRequest,
        assignments: list[StagingAssignment],
        infeasible: list[int],
        notes: list[str],
    ) -> StagingDiagnostics:
        req_sep = required_separation(self.profile, self.safety)
        if not assignments:
            return StagingDiagnostics(
                label=request.label,
                eventBeginsAt=request.requiredArrivalTime,
                requiredSeparation=req_sep,
                notes=[*notes, "no drones staged"],
            )

        begins = min(a.startTime for a in assignments)
        min_sep = self._min_separation(assignments, begins, request.requiredArrivalTime)
        rejected = bool(infeasible) or min_sep < req_sep
        if min_sep < req_sep:
            notes.append(
                f"predicted staging separation {min_sep:.2f} m below required {req_sep:.2f} m"
            )
        return StagingDiagnostics(
            label=request.label,
            droneCount=len(assignments),
            stagingBeginsAt=round(begins, 4),
            eventBeginsAt=round(request.requiredArrivalTime, 4),
            darkTravelDuration=round(request.requiredArrivalTime - begins, 4),
            maximumStagingVelocity=round(max(a.window.maximumVelocity for a in assignments), 4),
            maximumStagingAcceleration=round(max(a.window.maximumAcceleration for a in assignments), 4),
            minimumPredictedSeparation=round(min_sep, 4) if math.isfinite(min_sep) else -1.0,
            requiredSeparation=round(req_sep, 4),
            infeasibleDrones=sorted(infeasible),
            rejected=rejected,
            notes=notes,
        )

    def _min_separation(self, assignments: list[StagingAssignment], t0: float, t1: float) -> float:
        """Predict with the segment the compiler will actually emit.

        Re-deriving the motion here is how a planner ends up certifying a
        flight nobody flies.
        """
        if len(assignments) < 2:
            return math.inf
        segments = [
            TrajectorySegment(
                startTime=a.startTime,
                duration=max(a.arrivalTime - a.startTime, 1e-3),
                start=a.fromPosition,
                end=a.toPosition,
                waypoints=a.waypoints,
                style=a.style,
            )
            for a in assignments
        ]
        steps = self.samples * max(len(a.waypoints) + 1 for a in assignments)
        best = math.inf
        for k in range(steps + 1):
            t = t0 + (t1 - t0) * (k / steps)
            frame = np.array([s.position(t) for s in segments], dtype=np.float64)
            d, _ = cKDTree(frame).query(frame, k=2)
            best = min(best, float(d[:, 1].min()))
        return best
