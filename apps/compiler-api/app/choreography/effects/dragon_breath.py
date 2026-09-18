"""Dragon breath: an igniting plume leaving an aperture.

Demonstration effect only. Nothing about dragons lives in the trajectory
engine, the allocator or the staging planner.

The particles do not erupt from a single point. Sixty-four aircraft cannot
leave one aperture and stay 3.7 m apart, so the plume is a lattice of
stations that breathes outward as one body, and the fire is carried by an
ignition wave travelling along it. Appearance moves faster than the aircraft
do, which is the whole reason lighting and motion are separate tracks.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from app.choreography.effects.base import (
    Effect,
    EffectContext,
    EffectSample,
    EffectTarget,
    register_effect,
)
from app.choreography.scene import EffectSpec

Vec3 = tuple[float, float, float]
Rgb = tuple[float, float, float]

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))
MASK64 = 0xFFFFFFFFFFFFFFFF


def _hash01(*parts: int) -> float:
    """Platform-stable deterministic scalar in [0, 1).

    Independent of the drone count so particle i keeps its identity when the
    allocator hands the effect a different number of drones.
    """
    h = 0x9E3779B97F4A7C15
    for p in parts:
        h = (h ^ (int(p) & MASK64)) & MASK64
        h = (h * 0xBF58476D1CE4E5B9) & MASK64
        h ^= h >> 31
        h = (h * 0x94D049BB133111EB) & MASK64
        h ^= h >> 29
    return (h >> 11) / float(1 << 53)


def _unit(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-9:
        return (1.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 - edge0 <= 1e-9:
        return 1.0 if x >= edge1 else 0.0
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


class ColorStop(BaseModel):
    stop: float
    rgbLinear: Rgb


DEFAULT_GRADIENT = [
    ColorStop(stop=0.00, rgbLinear=(1.00, 0.94, 0.72)),
    ColorStop(stop=0.14, rgbLinear=(1.00, 0.74, 0.22)),
    ColorStop(stop=0.38, rgbLinear=(1.00, 0.44, 0.06)),
    ColorStop(stop=0.66, rgbLinear=(0.92, 0.18, 0.02)),
    ColorStop(stop=0.86, rgbLinear=(0.54, 0.05, 0.01)),
    ColorStop(stop=1.00, rgbLinear=(0.16, 0.01, 0.00)),
]


class DragonBreathParams(BaseModel):
    anchorPosition: Vec3 | None = None
    direction: Vec3 = (1.0, 0.0, 0.14)
    coneAngleDeg: float = 24.0
    lengthM: float = 44.0
    spreadM: float = 11.0
    turbulenceSeed: int = 7
    turbulenceM: float = 2.0
    apertureScale: float = 1.12

    # How far the plume grows, as a fraction of its own length. The growth is
    # a homothety about the aperture, so it can only push stations further
    # apart, never closer.
    breathFraction: float = 0.34
    # Turbulence is expressed as a fraction of the clearance the breath has
    # opened up, so it is zero at ignition and can never close a gap.
    turbulenceFraction: float = 0.34
    # Ignition wave: how far past the tip the front runs, and how long a
    # station stays lit once the front reaches it.
    frontOvershoot: float = 0.22
    emberLife: float = 0.46
    colorGradient: list[ColorStop] = Field(default_factory=lambda: list(DEFAULT_GRADIENT))

    def color_at(self, l: float) -> Rgb:
        stops = self.colorGradient or DEFAULT_GRADIENT
        if l <= stops[0].stop:
            return stops[0].rgbLinear
        for a, b in zip(stops, stops[1:], strict=False):
            if l <= b.stop:
                span = b.stop - a.stop
                u = 0.0 if span <= 1e-9 else (l - a.stop) / span
                return (
                    a.rgbLinear[0] + u * (b.rgbLinear[0] - a.rgbLinear[0]),
                    a.rgbLinear[1] + u * (b.rgbLinear[1] - a.rgbLinear[1]),
                    a.rgbLinear[2] + u * (b.rgbLinear[2] - a.rgbLinear[2]),
                )
        return stops[-1].rgbLinear


class Station(BaseModel):
    """Where one particle sits in the plume before it breathes."""

    offset: Vec3
    radial: Vec3
    tangent: Vec3
    axialFraction: float


def _apportion(total: int, capacities: list[int]) -> list[int]:
    """Split `total` across rings in proportion to capacity, exactly.

    Rounding each ring independently leaves a remainder that has to be
    dumped somewhere, and anywhere it lands is too close to a station that
    is already there. Largest-remainder apportionment lands on the total
    every time and never exceeds a ring's safe occupancy.
    """
    room = sum(capacities)
    if total <= 0 or room <= 0:
        return [0] * len(capacities)
    if total >= room:
        return list(capacities)
    exact = [total * c / room for c in capacities]
    out = [min(int(e), c) for e, c in zip(exact, capacities, strict=True)]
    order = sorted(
        range(len(capacities)),
        key=lambda j: (-(exact[j] - int(exact[j])), j),
    )
    cursor = 0
    while sum(out) < total:
        j = order[cursor % len(order)]
        if out[j] < capacities[j]:
            out[j] += 1
        cursor += 1
        if cursor > len(order) * (max(capacities) + 1):
            break
    return out


@register_effect
class DragonBreathEffect(Effect):
    type = "dragon-breath"

    def __init__(self, spec: EffectSpec) -> None:
        super().__init__(spec)
        self.params = DragonBreathParams(**(spec.parameters or {}))

    # --- geometry ---------------------------------------------------------

    def _frame(self) -> tuple[Vec3, Vec3, Vec3]:
        axis = _unit(self.params.direction)
        helper: Vec3 = (0.0, 0.0, 1.0)
        if abs(axis[2]) > 0.98:
            helper = (0.0, 1.0, 0.0)
        right = _unit(_cross(axis, helper))
        up = _unit(_cross(right, axis))
        return axis, right, up

    def _anchor(self, ctx: EffectContext) -> Vec3:
        return self.params.anchorPosition or ctx.anchor

    def _seed(self, ctx: EffectContext) -> int:
        return int(self.params.turbulenceSeed) * 1000003 + int(ctx.seed) + int(self.spec.seed)

    def scale_spatial(self, factor: float) -> bool:
        """Shorter, tighter breath. Ignition timing and identity are kept."""
        self.params = self.params.model_copy(
            update={
                "lengthM": self.params.lengthM * factor,
                "spreadM": self.params.spreadM * factor,
                "turbulenceM": self.params.turbulenceM * factor,
            }
        )
        return True

    # --- station lattice --------------------------------------------------

    def stations(self, ctx: EffectContext) -> list[Station]:
        """Ring lattice through the cone, spaced by the separation minimum.

        Rings are a safe distance apart along the axis and each ring holds
        only as many stations as its circumference allows, so the layout is
        legal by construction rather than by later repair.
        """
        p = self.params
        k = max(0, int(ctx.droneCount))
        if k == 0:
            return []
        axis, right, up = self._frame()
        sep = max(ctx.minSeparationM, 0.5)
        half_cone = math.tan(math.radians(p.coneAngleDeg) * 0.5)
        aperture = max(sep * 0.62 * p.apertureScale, sep * 0.55)

        rings = max(1, min(int(p.lengthM // sep), max(1, k)))
        layout: list[tuple[float, float, int]] = []
        for j in range(rings):
            frac = (j + 0.5) / rings
            radius = aperture + frac * p.lengthM * half_cone
            per = max(1, int((math.tau * radius) // sep))
            layout.append((frac, radius, per))

        shares = _apportion(k, [per for _f, _r, per in layout])

        out: list[Station] = []
        for j, (frac, radius, _per) in enumerate(layout):
            take = shares[j]
            if take <= 0:
                continue
            stagger = 0.5 * GOLDEN_ANGLE * j
            distance = frac * p.lengthM
            # One station on the axis reads as the core of the jet; more than
            # one has to sit on the ring or they would share a point.
            r = radius if take > 1 else 0.0
            for m in range(take):
                theta = stagger + math.tau * m / take
                radial: Vec3 = (
                    right[0] * math.cos(theta) + up[0] * math.sin(theta),
                    right[1] * math.cos(theta) + up[1] * math.sin(theta),
                    right[2] * math.cos(theta) + up[2] * math.sin(theta),
                )
                out.append(
                    Station(
                        offset=(
                            axis[0] * distance + radial[0] * r,
                            axis[1] * distance + radial[1] * r,
                            axis[2] * distance + radial[2] * r,
                        ),
                        radial=radial,
                        tangent=_cross(axis, radial),
                        axialFraction=frac,
                    )
                )
        return out[:k]

    def capacity_estimate(self, ctx: EffectContext) -> int:
        p = self.params
        sep = max(ctx.minSeparationM, 0.5)
        half_cone = math.tan(math.radians(p.coneAngleDeg) * 0.5)
        aperture = max(sep * 0.62 * p.apertureScale, sep * 0.55)
        rings = max(1, int(p.lengthM // sep))
        return sum(
            max(1, int((math.tau * (aperture + ((j + 0.5) / rings) * p.lengthM * half_cone)) // sep))
            for j in range(rings)
        )

    # --- sampling ---------------------------------------------------------

    def _breath(self, u: float) -> float:
        """Monotone-ish growth that ends extended: the plume travels outward."""
        return _smoothstep(0.0, 0.62, u) * (1.0 - 0.18 * _smoothstep(0.78, 1.0, u))

    def sample(self, u: float, ctx: EffectContext) -> EffectSample:
        u = min(1.0, max(0.0, float(u)))
        show_time = ctx.startTime + u * ctx.duration
        stations = self.stations(ctx)
        if not stations:
            return EffectSample(u=u, showTime=show_time, targets=[])

        p = self.params
        anchor = self._anchor(ctx)
        seed = self._seed(ctx)
        sep = max(ctx.minSeparationM, 0.5)

        growth = p.breathFraction * self._breath(u)
        scale = 1.0 + growth
        # Clearance the homothety just created, halved because two particles
        # can each wander toward the other.
        wander = min(p.turbulenceM, p.turbulenceFraction * sep * growth * 0.5)
        front = u * (1.0 + p.frontOvershoot)

        targets: list[EffectTarget] = []
        for i, station in enumerate(stations):
            phase = math.tau * _hash01(seed, i, 1)
            wobble = 0.7 + 1.5 * _hash01(seed, i, 2)
            flare = 0.78 + 0.34 * _hash01(seed, i, 3)
            lean = _hash01(seed, i, 4) - 0.5

            swirl = wander * math.sin(phase + u * math.tau * wobble)
            puff = wander * math.cos(phase * 1.7 + u * math.tau * wobble * 0.6)
            pos: Vec3 = (
                anchor[0] + station.offset[0] * scale + station.tangent[0] * swirl + station.radial[0] * puff,
                anchor[1] + station.offset[1] * scale + station.tangent[1] * swirl + station.radial[1] * puff,
                anchor[2] + station.offset[2] * scale + station.tangent[2] * swirl + station.radial[2] * puff,
            )

            # Ignition wave. The front outruns the aircraft, which is what
            # makes this read as fire rather than as a drifting cloud.
            age = front - station.axialFraction * (1.0 + 0.08 * lean)
            if age <= 0.0:
                targets.append(
                    EffectTarget(index=i, position=pos, rgbLinear=p.color_at(0.0), brightness=0.0)
                )
                continue
            life = min(1.0, age / max(p.emberLife, 1e-3))
            ignite = _smoothstep(0.0, 0.06, age)
            fade = 1.0 - _smoothstep(0.72, 1.0, life)
            flicker = 0.86 + 0.14 * math.sin(phase * 2.3 + u * math.tau * wobble * 3.1)
            brightness = min(1.0, ignite * fade * flare * flicker)
            targets.append(
                EffectTarget(
                    index=i,
                    position=pos,
                    rgbLinear=p.color_at(life),
                    brightness=max(0.0, brightness),
                )
            )

        return EffectSample(u=u, showTime=show_time, targets=targets)
