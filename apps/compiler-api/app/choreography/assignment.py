"""Assignment with explicit cost terms, plus an optional lookahead horizon.

Phase 1 is the existing pairwise engine with richer costs. Lookahead is opt-in
and bounded to 1–3 scenes; there is no whole-show global optimiser.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field
from scipy.optimize import linear_sum_assignment

from app.choreography.audience import AudienceView
from app.choreography.cost import CostWeights
from app.models import DroneAssignment, Formation
from app.transition.assign import MAX_EXACT_ASSIGNMENT as MAX_EXACT


class SceneAssignmentInputs(BaseModel):
    """Per-scene inputs the cost function needs beyond raw geometry."""

    importance: list[float] = Field(default_factory=list)
    roleIds: list[str] = Field(default_factory=list)
    brightness: list[float] = Field(default_factory=list)

    def importance_array(self, n: int) -> np.ndarray:
        if len(self.importance) >= n:
            return np.array(self.importance[:n], dtype=np.float64)
        return np.ones(n, dtype=np.float64)

    def brightness_array(self, n: int) -> np.ndarray:
        if len(self.brightness) >= n:
            return np.array(self.brightness[:n], dtype=np.float64)
        return np.ones(n, dtype=np.float64)


class AssignmentDiagnostics(BaseModel):
    horizon: int = 1
    movementCost: float = 0.0
    topologyCost: float = 0.0
    futureMovementCost: float = 0.0
    roleTransitionCost: float = 0.0
    visualDisruptionCost: float = 0.0
    totalCost: float = 0.0
    lookaheadImproved: bool = False
    baselineTotalCost: float = 0.0
    # False means the leg fell back to the greedy solver and carries no
    # separation bound; the conflict pass is then the only thing standing
    # between the show and a collision.
    exactSolve: bool = True


def _distance_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.linalg.norm(diff, axis=2)


def cost_terms(
    source: np.ndarray,
    target: np.ndarray,
    weights: CostWeights,
    *,
    src: SceneAssignmentInputs | None = None,
    dst: SceneAssignmentInputs | None = None,
    view: AudienceView | None = None,
    future: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """The five terms of `totalCost`, each as a source × target matrix.

    Defined in one place so the objective that is minimised and the
    diagnostics that are reported cannot drift apart. They had: the solver
    charged a tenth of the visual term the scorer printed, which made
    `lookaheadImproved` a coin flip.

    `future` is an already-solved downstream target per column, used for the
    lookahead detour term.
    """
    n = len(source)
    m = len(target)
    src = src or SceneAssignmentInputs()
    dst = dst or SceneAssignmentInputs()

    diff = source[:, None, :] - target[None, :, :]
    dist = np.linalg.norm(diff, axis=2)
    vertical = np.abs(diff[:, :, 2])
    importance = dst.importance_array(m)

    movement = weights.distance * dist * (1.0 + weights.featureImportance * importance[None, :])
    movement += weights.verticalPenalty * vertical

    # Keep neighbouring source indices going to neighbouring targets.
    topology = weights.topology * (
        np.abs(np.arange(n)[:, None] - np.arange(m)[None, :]) / max(n, 1)
    )

    role = np.zeros((n, m), dtype=np.float64)
    if src.roleIds and dst.roleIds:
        same = np.array(
            [[1.0 if a == b else 0.0 for b in dst.roleIds[:m]] for a in src.roleIds[:n]],
            dtype=np.float64,
        )
        role = weights.roleChangePenalty * (1.0 - same)

    # Motion the audience can actually register: lit, important and on screen.
    brightness = src.brightness_array(n)
    visibility = (
        np.array([view.visibility(tuple(p)) for p in source], dtype=np.float64)
        if view is not None
        else np.ones(n, dtype=np.float64)
    )
    visual = (
        weights.visualDisruption
        * dist
        * (brightness * visibility)[:, None]
        * importance[None, :]
    )

    detour = np.zeros((n, m), dtype=np.float64)
    if future is not None and len(future) == m:
        to_future = np.linalg.norm(target - future, axis=1)
        direct = np.linalg.norm(source[:, None, :] - future[None, :, :], axis=2)
        detour = weights.futureMovement * np.maximum(dist + to_future[None, :] - direct, 0.0)

    return {
        "movement": movement,
        "topology": topology,
        "future": detour,
        "role": role,
        "visual": visual,
    }


def build_cost_matrix(
    source: np.ndarray,
    target: np.ndarray,
    weights: CostWeights,
    *,
    src: SceneAssignmentInputs | None = None,
    dst: SceneAssignmentInputs | None = None,
    view: AudienceView | None = None,
    future: np.ndarray | None = None,
) -> np.ndarray:
    """Rows are source drones, columns are target points."""
    terms = cost_terms(source, target, weights, src=src, dst=dst, view=view, future=future)
    cost = sum(terms.values())
    return cost + np.arange(len(target))[None, :] * 1e-9  # deterministic ties


def solve_matrix(cost: np.ndarray) -> dict[int, int]:
    n = cost.shape[0]
    if n <= MAX_EXACT:
        rows, cols = linear_sum_assignment(cost)
        return {int(r): int(c) for r, c in zip(rows, cols, strict=True)}
    return _restricted(cost)


def _restricted(cost: np.ndarray) -> dict[int, int]:
    """Greedy nearest-free fallback for fleets too large to solve exactly.

    This returns a valid permutation but no separation guarantee whatsoever,
    so callers must report that the transition was not optimally assigned
    rather than presenting it as a checked result.
    """
    k = min(48, cost.shape[1])
    used: set[int] = set()
    mapping: dict[int, int] = {}
    order = np.argsort(cost.min(axis=1), kind="stable")
    for raw in order:
        i = int(raw)
        candidates = np.argpartition(cost[i], k - 1)[:k]
        for _, j in sorted((float(cost[i, j]), int(j)) for j in candidates):
            if j not in used:
                used.add(j)
                mapping[i] = j
                break
        if i not in mapping:
            leftover = next(j for j in range(cost.shape[1]) if j not in used)
            used.add(leftover)
            mapping[i] = leftover
    return mapping


def score_assignment(
    source: np.ndarray,
    target: np.ndarray,
    mapping: dict[int, int],
    weights: CostWeights,
    *,
    src: SceneAssignmentInputs | None = None,
    dst: SceneAssignmentInputs | None = None,
    view: AudienceView | None = None,
    future: np.ndarray | None = None,
) -> AssignmentDiagnostics:
    if not mapping:
        return AssignmentDiagnostics()

    rows = sorted(mapping)
    cols = [mapping[r] for r in rows]
    terms = cost_terms(source, target, weights, src=src, dst=dst, view=view, future=future)
    picked = {k: float(v[rows, cols].sum()) for k, v in terms.items()}
    return AssignmentDiagnostics(
        movementCost=round(picked["movement"], 4),
        topologyCost=round(picked["topology"], 4),
        futureMovementCost=round(picked["future"], 4),
        roleTransitionCost=round(picked["role"], 4),
        visualDisruptionCost=round(picked["visual"], 4),
        totalCost=round(sum(picked.values()), 4),
    )


def assign_pairwise(
    source: Formation,
    target: Formation,
    weights: CostWeights | None = None,
    *,
    src: SceneAssignmentInputs | None = None,
    view: AudienceView | None = None,
) -> list[DroneAssignment]:
    weights = weights or CostWeights()
    n = min(len(source.points), len(target.points))
    if n == 0:
        return []
    a = np.array([p.position for p in source.points[:n]], dtype=np.float64)
    b = np.array([p.position for p in target.points[:n]], dtype=np.float64)
    dst = SceneAssignmentInputs(importance=[p.importance for p in target.points[:n]])
    mapping = solve_matrix(build_cost_matrix(a, b, weights, src=src, dst=dst, view=view))
    return [
        DroneAssignment(droneId=i, fromPointId=i, toPointId=mapping.get(i, i % n)) for i in range(n)
    ]


def assign_with_lookahead(
    scenes: list[np.ndarray],
    weights: CostWeights | None = None,
    *,
    horizon: int = 1,
    inputs: list[SceneAssignmentInputs] | None = None,
    view: AudienceView | None = None,
) -> tuple[list[dict[int, int]], list[AssignmentDiagnostics]]:
    """Solve a chain of scenes, refining backward across `horizon` legs.

    horizon=1 is plain pairwise. horizon=2 lets A→B see B→C. horizon=3 lets
    A→B see B→C→D. Anything larger is clamped.
    """
    weights = weights or CostWeights()
    horizon = max(1, min(3, int(horizon)))
    legs = len(scenes) - 1
    if legs <= 0:
        return [], []

    inputs = inputs or [SceneAssignmentInputs() for _ in scenes]
    while len(inputs) < len(scenes):
        inputs.append(SceneAssignmentInputs())

    # Baseline: independent pairwise legs, left to right.
    baseline: list[dict[int, int]] = []
    for i in range(legs):
        cost = build_cost_matrix(
            scenes[i], scenes[i + 1], weights, src=inputs[i], dst=inputs[i + 1], view=view
        )
        baseline.append(solve_matrix(cost))

    mappings = [dict(m) for m in baseline]
    if horizon > 1:
        # Refine backward: each leg sees where its targets are already heading.
        for i in range(legs - 1, -1, -1):
            reach = min(horizon - 1, legs - 1 - i)
            if reach <= 0:
                continue
            future = _project_forward(scenes, mappings, i + 1, reach)
            cost = build_cost_matrix(
                scenes[i],
                scenes[i + 1],
                weights,
                src=inputs[i],
                dst=inputs[i + 1],
                view=view,
                future=future,
            )
            mappings[i] = solve_matrix(cost)

    diagnostics: list[AssignmentDiagnostics] = []
    for i in range(legs):
        reach = min(horizon - 1, legs - 1 - i)
        future = _project_forward(scenes, mappings, i + 1, reach) if reach > 0 else None
        d = score_assignment(
            scenes[i],
            scenes[i + 1],
            mappings[i],
            weights,
            src=inputs[i],
            dst=inputs[i + 1],
            view=view,
            future=future,
        )
        base = score_assignment(
            scenes[i],
            scenes[i + 1],
            baseline[i],
            weights,
            src=inputs[i],
            dst=inputs[i + 1],
            view=view,
            future=future,
        )
        d.horizon = horizon
        d.baselineTotalCost = base.totalCost
        d.lookaheadImproved = d.totalCost < base.totalCost - 1e-6
        d.exactSolve = len(scenes[i]) <= MAX_EXACT
        diagnostics.append(d)
    return mappings, diagnostics


def _project_forward(
    scenes: list[np.ndarray],
    mappings: list[dict[int, int]],
    scene_index: int,
    reach: int,
) -> np.ndarray:
    """Where each point of `scenes[scene_index]` ends up `reach` legs later."""
    current = scenes[scene_index]
    index = np.arange(len(current))
    for step in range(reach):
        leg = scene_index + step
        if leg >= len(mappings):
            break
        mapping = mappings[leg]
        nxt = scenes[leg + 1]
        index = np.array(
            [mapping.get(int(i), int(i) % max(len(nxt), 1)) for i in index], dtype=np.intp
        )
        current = nxt
    return current[np.clip(index, 0, len(current) - 1)]


def chain_total_cost(diagnostics: list[AssignmentDiagnostics]) -> float:
    return round(sum(d.totalCost for d in diagnostics), 4)
