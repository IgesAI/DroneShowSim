"""Physical validation of compiled programs.

Every physical drone is validated. Lighting is not an input to this module.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from app.choreography.conflict import ConflictGraph, detect_conflicts
from app.choreography.sampling import SampledShow, sample_programs, time_grid
from app.choreography.tracks import DroneProgram
from app.models import DroneProfile, SafetyMeasurement, SafetyProfile, Violation


class Geofence(BaseModel):
    groundZ: float = 0.0
    minAltitudeM: float = 1.0
    maxAltitudeM: float = 150.0
    radiusM: float = 400.0
    centerXY: tuple[float, float] = (0.0, 0.0)


class ProgramSafetyReport(BaseModel):
    passed: bool = True
    droneCount: int = 0
    darkDroneCount: int = 0
    validatedDroneCount: int = 0
    minimumSeparation: SafetyMeasurement
    maxHorizontalVelocity: SafetyMeasurement
    maxVerticalVelocity: SafetyMeasurement
    maxAcceleration: SafetyMeasurement
    maxJerk: SafetyMeasurement
    geofenceViolations: list[Violation] = Field(default_factory=list)
    altitudeViolations: list[Violation] = Field(default_factory=list)
    conflicts: ConflictGraph = Field(default_factory=ConflictGraph)


def validate_programs(
    programs: list[DroneProgram],
    profile: DroneProfile,
    safety: SafetyProfile,
    *,
    geofence: Geofence | None = None,
    hz: float = 8.0,
    end: float | None = None,
    sampled: SampledShow | None = None,
    visual_threshold: float = 0.02,
) -> ProgramSafetyReport:
    fence = geofence or Geofence()
    if not programs:
        zero = SafetyMeasurement(value=0.0, limit=0.0, passed=True)
        return ProgramSafetyReport(
            minimumSeparation=zero,
            maxHorizontalVelocity=zero,
            maxVerticalVelocity=zero,
            maxAcceleration=zero,
            maxJerk=zero,
        )

    duration = end if end is not None else max(p.trajectoryTrack.endTime for p in programs)
    if sampled is None:
        sampled = sample_programs(programs, time_grid(0.0, max(duration, 0.1), hz))

    t = sampled.times
    pos = sampled.positions
    vel = sampled.velocities
    acc = sampled.accelerations
    # Jerk is the one quantity the segments do not publish, so it costs a
    # single difference of the analytic acceleration. Deriving all three from
    # positions instead would compound the grid's error three times over.
    jerk = np.gradient(acc, t, axis=0)

    horiz = float(np.linalg.norm(vel[:, :, :2], axis=2).max())
    ascent = float(np.maximum(vel[:, :, 2], 0.0).max())
    descent = float(np.maximum(-vel[:, :, 2], 0.0).max())
    amax = float(np.linalg.norm(acc, axis=2).max())
    jmax = float(np.linalg.norm(jerk, axis=2).max())

    graph = detect_conflicts(programs, profile, safety, end=duration, hz=hz, sampled=sampled)

    altitude: list[Violation] = []
    geo: list[Violation] = []
    z = pos[:, :, 2]
    ceiling = np.nonzero(z > fence.maxAltitudeM)
    floor = np.nonzero(z < fence.groundZ - 1e-6)
    radial = np.hypot(pos[:, :, 0] - fence.centerXY[0], pos[:, :, 1] - fence.centerXY[1])
    outside = np.nonzero(radial > fence.radiusM)

    for arr, bucket, required, label in (
        (ceiling, altitude, fence.maxAltitudeM, "above ceiling"),
        (floor, altitude, fence.groundZ, "below ground"),
        (outside, geo, fence.radiusM, "outside lateral geofence"),
    ):
        for fi, di in list(zip(arr[0], arr[1], strict=True))[:24]:
            drone = sampled.droneIds[int(di)]
            measured = float(z[fi, di]) if bucket is altitude else float(radial[fi, di])
            bucket.append(
                Violation(
                    droneIds=[drone],
                    time=round(float(t[fi]), 4),
                    positions=[tuple(pos[fi, di])],  # type: ignore[list-item]
                    measured=round(measured, 4),
                    required=round(required, 4),
                    severity="error",
                    message=f"D{drone} {label} at {t[fi]:.2f}s",
                )
            )

    v_limit = max(profile.maxVerticalSpeedMps, profile.maxAscentSpeedMps, profile.maxDescentSpeedMps)
    dark = int((sampled.brightness <= visual_threshold).any(axis=0).sum())

    report = ProgramSafetyReport(
        droneCount=len(programs),
        darkDroneCount=dark,
        validatedDroneCount=len(programs),
        minimumSeparation=SafetyMeasurement(
            value=graph.minimumSeparation,
            limit=graph.requiredSeparation,
            passed=graph.passed,
        ),
        maxHorizontalVelocity=SafetyMeasurement(
            value=round(horiz, 4),
            limit=profile.maxHorizontalSpeedMps,
            passed=horiz <= profile.maxHorizontalSpeedMps + 1e-2,
        ),
        maxVerticalVelocity=SafetyMeasurement(
            value=round(max(ascent, descent), 4),
            limit=v_limit,
            passed=ascent <= profile.maxAscentSpeedMps + 1e-2 and descent <= profile.maxDescentSpeedMps + 1e-2,
        ),
        maxAcceleration=SafetyMeasurement(
            value=round(amax, 4),
            limit=profile.maxAccelerationMps2,
            passed=amax <= profile.maxAccelerationMps2 + 1e-1,
        ),
        maxJerk=SafetyMeasurement(
            value=round(jmax, 4),
            limit=profile.maxJerkMps3,
            passed=jmax <= profile.maxJerkMps3 + 0.5,
        ),
        geofenceViolations=geo,
        altitudeViolations=altitude,
        conflicts=graph,
    )
    report.passed = all(
        [
            report.minimumSeparation.passed,
            report.maxHorizontalVelocity.passed,
            report.maxVerticalVelocity.passed,
            report.maxAcceleration.passed,
            not geo,
            not altitude,
        ]
    )
    return report
