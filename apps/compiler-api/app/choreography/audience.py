"""Audience projection. Visual optimisation only — never a physical metric."""

from __future__ import annotations

import math

from pydantic import BaseModel

Vec3 = tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _unit(v: Vec3) -> Vec3:
    n = _norm(v)
    if n < 1e-9:
        return (0.0, 1.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class AudienceView(BaseModel):
    """A single representative viewpoint. Later this becomes a region."""

    position: Vec3 = (0.0, 90.0, 1.7)
    lookAt: Vec3 = (0.0, 0.0, 28.0)
    fovDeg: float = 38.0
    nearM: float = 1.0

    def forward(self) -> Vec3:
        return _unit(_sub(self.lookAt, self.position))

    def basis(self) -> tuple[Vec3, Vec3, Vec3]:
        fwd = self.forward()
        world_up: Vec3 = (0.0, 0.0, 1.0)
        if abs(_dot(fwd, world_up)) > 0.999:
            world_up = (0.0, 1.0, 0.0)
        right = _unit(_cross(fwd, world_up))
        up = _unit(_cross(right, fwd))
        return right, up, fwd

    def depth(self, position: Vec3) -> float:
        return _dot(_sub(position, self.position), self.forward())

    def project_to_audience(self, position: Vec3) -> tuple[float, float]:
        """Normalised image-plane coordinates. (0,0) is the centre of view."""
        right, up, fwd = self.basis()
        rel = _sub(position, self.position)
        d = _dot(rel, fwd)
        if d <= self.nearM:
            d = self.nearM
        k = 1.0 / (d * math.tan(math.radians(self.fovDeg) * 0.5))
        return (_dot(rel, right) * k, _dot(rel, up) * k)

    def visibility(self, position: Vec3) -> float:
        """0..1 weight for how much the audience can register motion here."""
        if self.depth(position) <= self.nearM:
            return 0.0
        x, y = self.project_to_audience(position)
        r = math.hypot(x, y)
        if r <= 1.0:
            return 1.0
        return max(0.0, 1.0 - (r - 1.0))

    def angular_separation(self, a: Vec3, b: Vec3) -> float:
        ax, ay = self.project_to_audience(a)
        bx, by = self.project_to_audience(b)
        return math.hypot(ax - bx, ay - by)

    def behind_offset(self, position: Vec3, meters: float) -> Vec3:
        """A point `meters` further from the audience — useful for staging."""
        fwd = self.forward()
        return (
            position[0] + fwd[0] * meters,
            position[1] + fwd[1] * meters,
            position[2] + fwd[2] * meters,
        )
