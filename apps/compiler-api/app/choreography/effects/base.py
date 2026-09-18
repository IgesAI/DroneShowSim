"""Generic effect interface.

An effect is a time-varying formation generator. It receives time, an anchor, a
requested drone count and parameters, and returns desired target positions and
lighting. It never owns drone IDs and never writes trajectories.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from app.choreography.scene import EffectSpec, ResourceRequest
from app.choreography.tracks import LightingKeyframe

Vec3 = tuple[float, float, float]
Rgb = tuple[float, float, float]


class EffectContext(BaseModel):
    """Everything an effect needs that it cannot know by itself."""

    anchor: Vec3 = (0.0, 0.0, 30.0)
    droneCount: int = 0
    minSeparationM: float = 3.0
    seed: int = 1
    startTime: float = 0.0
    duration: float = 4.0


class EffectTarget(BaseModel):
    index: int
    position: Vec3
    rgbLinear: Rgb = (1.0, 1.0, 1.0)
    brightness: float = 1.0


class EffectSample(BaseModel):
    u: float
    showTime: float
    targets: list[EffectTarget] = Field(default_factory=list)

    def positions(self) -> list[Vec3]:
        return [t.position for t in self.targets]


class Effect(ABC):
    """Deterministic given identical parameters and seed."""

    type: str = "effect"

    def __init__(self, spec: EffectSpec) -> None:
        self.spec = spec
        self.id = spec.id
        self.name = spec.name or spec.id

    def resource_request(self) -> ResourceRequest:
        return self.spec.resources

    @abstractmethod
    def sample(self, u: float, ctx: EffectContext) -> EffectSample: ...

    def entry_targets(self, ctx: EffectContext) -> list[EffectTarget]:
        """Where allocated drones must already be when the effect begins."""
        return self.sample(0.0, ctx).targets

    def exit_targets(self, ctx: EffectContext) -> list[EffectTarget]:
        return self.sample(1.0, ctx).targets

    def lighting_keyframes(self, index: int, ctx: EffectContext, resolution: int = 12) -> list[LightingKeyframe]:
        """Sample the effect's own colour curve into the lighting track."""
        keys: list[LightingKeyframe] = []
        for k in range(resolution + 1):
            u = k / resolution
            sample = self.sample(u, ctx)
            if index >= len(sample.targets):
                break
            target = sample.targets[index]
            keys.append(
                LightingKeyframe(
                    time=ctx.startTime + u * ctx.duration,
                    rgbLinear=target.rgbLinear,
                    brightness=target.brightness,
                    interpolation="linear",
                )
            )
        return keys

    def max_travel(self, ctx: EffectContext) -> float:
        entry = self.entry_targets(ctx)
        exit_ = self.exit_targets(ctx)
        return max(
            (math.dist(a.position, b.position) for a, b in zip(entry, exit_, strict=False)),
            default=0.0,
        )

    # --- physical envelope -------------------------------------------------

    def peak_kinematics(self, ctx: EffectContext, resolution: int = 48) -> tuple[float, float, float]:
        """Speed, acceleration and jerk the effect demands as authored.

        Speed alone is not enough to know whether an aircraft can fly this. A
        plume that never exceeds 3 m/s but wobbles twice a second asks for more
        acceleration than a multirotor show profile allows, and the drone that
        cannot deliver it simply flies somewhere else.
        """
        if ctx.duration <= 1e-6 or ctx.droneCount <= 0:
            return 0.0, 0.0, 0.0
        dt = ctx.duration / resolution
        frames = [
            np.asarray(self.sample(k / resolution, ctx).positions(), dtype=np.float64)
            for k in range(resolution + 1)
        ]
        if not frames or frames[0].size == 0:
            return 0.0, 0.0, 0.0
        p = np.stack(frames)
        vel = np.diff(p, axis=0) / dt
        acc = np.diff(vel, axis=0) / dt if len(vel) > 1 else np.zeros((1, *p.shape[1:]))
        jrk = np.diff(acc, axis=0) / dt if len(acc) > 1 else np.zeros((1, *p.shape[1:]))
        return (
            float(np.linalg.norm(vel, axis=-1).max()),
            float(np.linalg.norm(acc, axis=-1).max()),
            float(np.linalg.norm(jrk, axis=-1).max()),
        )

    def peak_speed(self, ctx: EffectContext, resolution: int = 36) -> float:
        """Fastest a drone would have to fly to realise the effect as authored."""
        return self.peak_kinematics(ctx, resolution)[0]

    def scale_spatial(self, factor: float) -> bool:
        """Shrink the effect to fit the flight envelope.

        Effects that cannot be scaled return False and the compiler reports
        the overspeed instead of silently flying something impossible.
        """
        return False

    # --- capacity ----------------------------------------------------------

    def min_internal_separation(self, ctx: EffectContext, resolution: int = 24) -> float:
        """Closest two of this effect's own targets ever come to each other."""
        if ctx.droneCount < 2:
            return math.inf
        worst = math.inf
        for k in range(resolution + 1):
            pts = np.asarray(self.sample(k / resolution, ctx).positions(), dtype=np.float64)
            if len(pts) < 2:
                continue
            d, _ = cKDTree(pts).query(pts, k=2)
            worst = min(worst, float(d[:, 1].min()))
        return worst

    def max_safe_count(self, ctx: EffectContext, ceiling: int) -> int:
        """Largest drone count the geometry can hold at safe spacing.

        A plume shrunk to fit the speed limit cannot also hold every drone
        that was requested. Asking the effect rather than guessing keeps the
        allocation honest instead of handing the repair pass an impossible
        arrangement.
        """
        if ceiling < 2:
            return max(ceiling, 0)
        lo, hi = 1, ceiling
        if self.min_internal_separation(ctx.model_copy(update={"droneCount": hi})) >= ctx.minSeparationM:
            return hi
        while lo < hi - 1:
            mid = (lo + hi) // 2
            probe = ctx.model_copy(update={"droneCount": mid})
            if self.min_internal_separation(probe) >= ctx.minSeparationM:
                lo = mid
            else:
                hi = mid
        return lo


class EnvelopeLimits(BaseModel):
    """What the aircraft will actually do, as opposed to what looks good."""

    speed: float = 0.0
    acceleration: float = 0.0
    jerk: float = 0.0

    def worst_ratio(self, speed: float, acceleration: float, jerk: float) -> float:
        """How far outside the envelope the effect sits, as a single number."""
        return max(
            speed / self.speed if self.speed > 0 else 0.0,
            acceleration / self.acceleration if self.acceleration > 0 else 0.0,
            jerk / self.jerk if self.jerk > 0 else 0.0,
        )

    def required_stretch(self, speed: float, acceleration: float, jerk: float) -> float:
        """Smallest time stretch that brings all three inside the envelope.

        Each derivative responds differently: stretching by k divides speed by
        k, acceleration by k² and jerk by k³. Treating them alike and slowing
        by the raw jerk ratio turns an 8-second plume into a 33-second one to
        fix an overshoot that 1.6× would have cleared.
        """
        need = 1.0
        if self.speed > 0 and speed > 0:
            need = max(need, speed / self.speed)
        if self.acceleration > 0 and acceleration > 0:
            need = max(need, math.sqrt(acceleration / self.acceleration))
        if self.jerk > 0 and jerk > 0:
            need = max(need, (jerk / self.jerk) ** (1.0 / 3.0))
        return need


class EffectFit(BaseModel):
    effectId: str
    peakSpeedBefore: float = 0.0
    peakSpeedAfter: float = 0.0
    peakAccelBefore: float = 0.0
    peakAccelAfter: float = 0.0
    peakJerkBefore: float = 0.0
    peakJerkAfter: float = 0.0
    speedLimit: float = 0.0
    accelLimit: float = 0.0
    jerkLimit: float = 0.0
    spatialScale: float = 1.0
    timeStretch: float = 1.0
    durationBefore: float = 0.0
    durationAfter: float = 0.0
    capacity: int = 0
    exceedsEnvelope: bool = False
    notes: list[str] = Field(default_factory=list)


def fit_effect_to_envelope(
    effect: "Effect",
    ctx: EffectContext,
    limits: EnvelopeLimits,
    *,
    max_time_stretch: float = 6.0,
    passes: int = 5,
) -> tuple[EffectFit, EffectContext]:
    """Bring an authored effect inside the flight envelope.

    Time is stretched before space is shrunk. Both reduce the demand, but
    shrinking a plume also shrinks the room its particles have to stay apart,
    so a 64-drone plume squeezed to 30% of its authored size has nowhere to
    put anyone. Slowing it down costs show seconds and nothing else.

    Stretching by k divides speed by k, acceleration by k² and jerk by k³, so
    the binding constraint is usually jerk and one pass lands close.
    """
    v0, a0, j0 = effect.peak_kinematics(ctx)
    fit = EffectFit(
        effectId=effect.id,
        peakSpeedBefore=round(v0, 4),
        peakSpeedAfter=round(v0, 4),
        peakAccelBefore=round(a0, 4),
        peakAccelAfter=round(a0, 4),
        peakJerkBefore=round(j0, 4),
        peakJerkAfter=round(j0, 4),
        speedLimit=round(limits.speed, 4),
        accelLimit=round(limits.acceleration, 4),
        jerkLimit=round(limits.jerk, 4),
        durationBefore=round(ctx.duration, 4),
        durationAfter=round(ctx.duration, 4),
    )

    v, a, j = v0, a0, j0
    total_stretch = 1.0
    for _ in range(passes):
        step = limits.required_stretch(v, a, j)
        if step <= 1.0 + 1e-6 or total_stretch >= max_time_stretch - 1e-6:
            break
        step = min(step, max_time_stretch / total_stretch)
        ctx = ctx.model_copy(update={"duration": ctx.duration * step})
        total_stretch *= step
        v, a, j = effect.peak_kinematics(ctx)
    if total_stretch > 1.0 + 1e-6:
        fit.timeStretch = round(total_stretch, 6)
        fit.notes.append(
            f"slowed {total_stretch:.2f}× to {ctx.duration:.1f}s instead of shrinking the geometry"
        )

    spatial = 1.0
    for _ in range(passes):
        ratio = limits.worst_ratio(v, a, j)
        if ratio <= 1.0:
            break
        factor = max(1.0 / ratio, 0.25)
        if not effect.scale_spatial(factor):
            break
        spatial *= factor
        v, a, j = effect.peak_kinematics(ctx)
    fit.spatialScale = round(spatial, 6)
    if spatial < 1.0 - 1e-6:
        fit.notes.append(f"scaled {spatial:.2f}× after the time budget ran out")

    fit.peakSpeedAfter = round(v, 4)
    fit.peakAccelAfter = round(a, 4)
    fit.peakJerkAfter = round(j, 4)
    fit.exceedsEnvelope = limits.worst_ratio(v, a, j) > 1.02
    fit.durationAfter = round(ctx.duration, 4)
    fit.capacity = effect.max_safe_count(ctx, ctx.droneCount)
    if fit.capacity < ctx.droneCount:
        fit.notes.append(
            f"geometry holds {fit.capacity} drones at {ctx.minSeparationM:.1f} m, not {ctx.droneCount}"
        )
    return fit, ctx


_REGISTRY: dict[str, type[Effect]] = {}


def register_effect(cls: type[Effect]) -> type[Effect]:
    _REGISTRY[cls.type] = cls
    return cls


def build_effect(spec: EffectSpec) -> Effect:
    cls = _REGISTRY.get(spec.type)
    if cls is None:
        raise ValueError(f"unknown effect type: {spec.type}")
    return cls(spec)


def known_effect_types() -> list[str]:
    return sorted(_REGISTRY)
