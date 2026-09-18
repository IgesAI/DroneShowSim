from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from app.models import (
    DroneAssignment,
    DroneProfile,
    Formation,
    SafetyMeasurement,
    SafetyProfile,
    SafetyReport,
    Violation,
    required_separation,
)
from app.safety.geometry import closing_speeds, segment_distances
from app.trajectory.minjerk import PEAK_S1, min_duration
from app.trajectory.segment import PATH_SCALE, sample_transition

CompileMode = str  # "preview" | "full"


def recommended_duration(
    source: Formation,
    target: Formation,
    assignment: list[DroneAssignment],
    profile: DroneProfile,
    style: str = "morph",
) -> float:
    if not assignment:
        return 0.4
    p0 = np.array([source.points[a.fromPointId].position for a in assignment], dtype=np.float64)
    p1 = np.array([target.points[a.toPointId].position for a in assignment], dtype=np.float64)
    d = np.linalg.norm(p1 - p0, axis=1)
    dz = p1[:, 2] - p0[:, 2]
    t = np.array([min_duration(float(di), profile.maxHorizontalSpeedMps, profile.maxAccelerationMps2) for di in d])
    climb = dz > 0
    drop = dz < 0
    t[climb] = np.maximum(t[climb], PEAK_S1 * dz[climb] / max(profile.maxAscentSpeedMps, 0.1))
    t[drop] = np.maximum(t[drop], PEAK_S1 * (-dz[drop]) / max(profile.maxDescentSpeedMps, 0.1))
    return float(t.max(initial=0.4)) * PATH_SCALE.get(style, 1.0)


def _sample_hz(mode: str, phase: str) -> float:
    if phase in {"takeoff", "landing"}:
        return 2.0 if mode == "preview" else 4.0
    return 4.0 if mode == "preview" else 12.0


def validate_transition(
    source: Formation,
    target: Formation,
    assignment: list[DroneAssignment],
    duration: float,
    profile: DroneProfile,
    safety: SafetyProfile,
    hz: float | None = None,
    phase: str = "show",
    style: str = "morph",
    mode: CompileMode = "preview",
) -> SafetyReport:
    base = required_separation(profile, safety)
    if phase in {"takeoff", "landing"}:
        base = max(base, safety.takeoffSeparationM)
    p0 = np.array([source.points[a.fromPointId].position for a in assignment], dtype=np.float64)
    p1 = np.array([target.points[a.toPointId].position for a in assignment], dtype=np.float64)
    rec = recommended_duration(source, target, assignment, profile, style)

    hz = hz if hz is not None else _sample_hz(mode, phase)
    use_segments = mode == "full"
    frames = max(2, int(duration * hz) + 1)
    t = np.linspace(0.0, duration, frames)
    u = t / max(duration, 1e-6)
    pos = sample_transition(p0, p1, u, style)
    vel = np.gradient(pos, t, axis=0)
    acc = np.gradient(vel, t, axis=0)

    horiz = np.linalg.norm(vel[:, :, :2], axis=2).max()
    ascent = np.maximum(vel[:, :, 2], 0.0).max()
    descent = np.maximum(-vel[:, :, 2], 0.0).max()
    vert = max(ascent, descent)
    amax = np.linalg.norm(acc, axis=2).max()
    jerk = np.gradient(acc, t, axis=0)
    jmax = np.linalg.norm(jerk, axis=2).max()

    prox: list[Violation] = []
    min_sep = math.inf
    worst_req = base
    search_r = max(base * 2.5, 4.0)
    static = (
        profile.minimumSeparationM
        + profile.radiusM * 2
        + safety.navigationUncertaintyM
        + safety.windAllowanceM
        + safety.operatorMarginM
    )
    if phase in {"takeoff", "landing"}:
        static = max(static, safety.takeoffSeparationM)
    vfactor = safety.velocitySeparationFactor

    for fi in range(len(pos)):
        frame = pos[fi]
        pairs = np.array(list(cKDTree(frame).query_pairs(search_r)), dtype=np.intp)
        if len(pairs) == 0:
            continue
        ia, ja = pairs[:, 0], pairs[:, 1]
        d_now = np.linalg.norm(frame[ia] - frame[ja], axis=1)
        close = closing_speeds(frame[ia], frame[ja], vel[fi, ia], vel[fi, ja])
        if use_segments and fi + 1 < len(pos):
            d_seg, u_seg = segment_distances(pos[fi, ia], pos[fi + 1, ia], pos[fi, ja], pos[fi + 1, ja])
            measured = np.minimum(d_now, d_seg)
        else:
            u_seg = np.zeros(len(ia), dtype=np.float64)
            measured = d_now
        req = static + np.maximum(close, 0.0) * vfactor
        min_sep = min(min_sep, float(measured.min()))
        worst_req = max(worst_req, float(req.max()))
        bad = np.nonzero(measured < req)[0]
        for k in bad:
            if len(prox) >= 48:
                break
            when = float(t[fi] + float(u_seg[k]) * (t[min(fi + 1, len(t) - 1)] - t[fi]))
            i, j = int(ia[k]), int(ja[k])
            prox.append(
                Violation(
                    droneIds=[assignment[i].droneId, assignment[j].droneId],
                    time=when,
                    positions=[tuple(frame[i]), tuple(frame[j])],
                    measured=float(measured[k]),
                    required=float(req[k]),
                    severity="error",
                    phase=phase,  # type: ignore[arg-type]
                    closingSpeedMps=float(close[k]),
                    message=(
                        f"D{assignment[i].droneId} <-> D{assignment[j].droneId} "
                        f"at {when:.3f}s during {phase}: {measured[k]:.2f}m < {req[k]:.2f}m capsule "
                        f"(closing {close[k]:.1f} m/s)"
                    ),
                )
            )

    if not math.isfinite(min_sep):
        min_sep = base
    v_limit = max(profile.maxVerticalSpeedMps, profile.maxAscentSpeedMps, profile.maxDescentSpeedMps)
    report = SafetyReport(
        passed=True,
        minimumSeparation=SafetyMeasurement(value=float(min_sep), limit=worst_req, passed=min_sep >= worst_req * 0.999),
        maxHorizontalVelocity=SafetyMeasurement(value=float(horiz), limit=profile.maxHorizontalSpeedMps, passed=horiz <= profile.maxHorizontalSpeedMps + 1e-3),
        maxVerticalVelocity=SafetyMeasurement(
            value=float(vert),
            limit=v_limit,
            passed=ascent <= profile.maxAscentSpeedMps + 1e-3 and descent <= profile.maxDescentSpeedMps + 1e-3,
        ),
        maxAcceleration=SafetyMeasurement(value=float(amax), limit=profile.maxAccelerationMps2, passed=amax <= profile.maxAccelerationMps2 + 1e-3),
        maxJerk=SafetyMeasurement(value=float(jmax), limit=profile.maxJerkMps3, passed=jmax <= profile.maxJerkMps3 + 0.5),
        proximityViolations=prox,
        recommendedDuration=rec,
    )
    report.passed = all(
        [
            report.minimumSeparation.passed,
            report.maxHorizontalVelocity.passed,
            report.maxVerticalVelocity.passed,
            report.maxAcceleration.passed,
            len(prox) == 0,
        ]
    )
    return report
