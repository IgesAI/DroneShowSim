"""Effect resource allocation.

Effects request capacity; this module decides which physical drones serve the
request. Selection prefers low-importance formation points so the silhouette
survives, and breaks ties by drone id so results are reproducible.
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field
from scipy.optimize import linear_sum_assignment

from app.choreography.scene import ResourceRequest
from app.choreography.tracks import RoleType

Vec3 = tuple[float, float, float]


class AllocationCandidate(BaseModel):
    droneId: int
    position: Vec3
    importance: float = 1.0
    roleType: RoleType = "FORMATION"
    roleId: str = ""
    formationPointId: int | None = None
    brightness: float = 1.0


class ImpactEstimator(Protocol):
    """Swap in a perceptual metric later without touching the allocator."""

    name: str

    def estimate(self, removed: list[AllocationCandidate]) -> float: ...


class SummedImportanceImpact:
    name = "summed-importance"

    def estimate(self, removed: list[AllocationCandidate]) -> float:
        return round(sum(c.importance for c in removed), 6)


class AllocationDiagnostics(BaseModel):
    effectId: str
    requestedDroneCount: int
    allocatedDroneCount: int
    sourceRoles: dict[str, int] = Field(default_factory=dict)
    formationImpactEstimate: float = 0.0
    impactMetric: str = "summed-importance"
    removedImportance: float = 0.0
    highestRemovedImportance: float = 0.0
    importanceCeiling: float = 1.0
    satisfied: bool = True
    shortfallReason: str = ""


class AllocationResult(BaseModel):
    effectId: str
    droneIds: list[int] = Field(default_factory=list)
    candidates: list[AllocationCandidate] = Field(default_factory=list)
    diagnostics: AllocationDiagnostics


def allocate_effect_drones(
    effect_id: str,
    request: ResourceRequest,
    candidates: list[AllocationCandidate],
    anchor: Vec3,
    *,
    importance_weight: float = 6.0,
    estimator: ImpactEstimator | None = None,
    protected: set[int] | None = None,
) -> AllocationResult:
    """Pick drones for one effect.

    `importance_weight` is expressed in metres: how far the allocator will fly
    a drone to avoid deleting one unit of visual importance.
    """
    estimator = estimator or SummedImportanceImpact()
    protected = protected or set()
    pool = [c for c in candidates if c.droneId not in protected]

    def score(c: AllocationCandidate) -> tuple[float, int]:
        travel = math.dist(c.position, anchor)
        return (travel + importance_weight * c.importance, c.droneId)

    # Hold the importance ceiling if it can be held, and say so when it
    # cannot. Raising it silently is how a show loses an eye to a firework.
    ceiling = request.maxBorrowImportance
    eligible = [c for c in pool if c.importance <= ceiling + 1e-9]
    relaxed = 0.0
    while len(eligible) < request.minimum and ceiling < 1.0:
        ceiling = min(1.0, ceiling + 0.1)
        relaxed = ceiling
        eligible = [c for c in pool if c.importance <= ceiling + 1e-9]
    if len(eligible) < request.minimum:
        eligible = pool
        relaxed = 1.0

    want = request.clamp(len(eligible))
    chosen = sorted(eligible, key=score)[:want]
    chosen.sort(key=lambda c: c.droneId)

    source_roles: dict[str, int] = {}
    for c in chosen:
        key = f"{c.roleType}:{c.roleId}" if c.roleId else c.roleType
        source_roles[key] = source_roles.get(key, 0) + 1

    impact = estimator.estimate(chosen)
    satisfied = request.satisfied_by(len(chosen))
    reason = ""
    if not satisfied:
        reason = (
            f"only {len(chosen)} drones available for minimum {request.minimum}"
            if len(pool) < request.minimum
            else "allocation clamped below minimum"
        )
    elif relaxed:
        reason = (
            f"importance ceiling raised from {request.maxBorrowImportance:.2f} to "
            f"{relaxed:.2f} to reach the minimum of {request.minimum}"
        )

    return AllocationResult(
        effectId=effect_id,
        droneIds=[c.droneId for c in chosen],
        candidates=chosen,
        diagnostics=AllocationDiagnostics(
            effectId=effect_id,
            requestedDroneCount=request.preferred,
            allocatedDroneCount=len(chosen),
            sourceRoles=dict(sorted(source_roles.items())),
            formationImpactEstimate=impact,
            impactMetric=estimator.name,
            removedImportance=round(sum(c.importance for c in chosen), 6),
            highestRemovedImportance=round(max((c.importance for c in chosen), default=0.0), 6),
            importanceCeiling=round(ceiling, 6),
            satisfied=satisfied,
            shortfallReason=reason,
        ),
    )


def match_to_targets(
    candidates: list[AllocationCandidate],
    targets: list[Vec3],
) -> list[tuple[AllocationCandidate, int]]:
    """Optimal matching on squared distance.

    Squared cost is what buys the separation guarantee: if no swap of two
    destinations lowers the sum, then every pair of drones satisfies
    <a_i - a_j, b_i - b_j> >= 0 and a synchronised flight between the two
    configurations stays at least min(start, end) / sqrt(2) apart. Plain
    distance gives no such bound and lets staging paths pass within
    centimetres.
    """
    ordered = sorted(candidates, key=lambda c: c.droneId)
    if not ordered or not targets:
        return []
    src = np.array([c.position for c in ordered], dtype=np.float64)
    dst = np.array(targets, dtype=np.float64)
    diff = src[:, None, :] - dst[None, :, :]
    cost = (diff * diff).sum(axis=2)
    cost += np.arange(len(dst))[None, :] * 1e-9  # deterministic ties
    rows, cols = linear_sum_assignment(cost)
    return [(ordered[int(r)], int(c)) for r, c in zip(rows, cols, strict=True)]
