"""Assignment costs and the bounded lookahead horizon."""

import numpy as np
import pytest

from app.choreography.assignment import (
    SceneAssignmentInputs,
    assign_pairwise,
    assign_with_lookahead,
    build_cost_matrix,
    chain_total_cost,
    solve_matrix,
)
from app.choreography.audience import AudienceView
from app.choreography.cost import CostWeights
from app.models import Formation, FormationPoint


def _formation(fid: str, positions, importance=None) -> Formation:
    return Formation(
        id=fid,
        name=fid,
        sourceAssetId="x",
        points=[
            FormationPoint(
                id=i,
                position=p,
                importance=1.0 if importance is None else importance[i],
            )
            for i, p in enumerate(positions)
        ],
    )


def _row(n: int, y: float, spacing: float = 6.0) -> list[tuple[float, float, float]]:
    return [(i * spacing, y, 40.0) for i in range(n)]


# ------------------------------------------------------------- 9. pairwise


def test_pairwise_assignment_works_with_lookahead_disabled():
    src, dst = _formation("a", _row(8, 0.0)), _formation("b", _row(8, 30.0))
    result = assign_pairwise(src, dst)
    assert len(result) == 8
    assert {a.toPointId for a in result} == set(range(8))


def test_pairwise_picks_the_obvious_pairing():
    src = _formation("a", [(0.0, 0.0, 40.0), (50.0, 0.0, 40.0)])
    dst = _formation("b", [(52.0, 0.0, 40.0), (2.0, 0.0, 40.0)])
    mapping = {a.droneId: a.toPointId for a in assign_pairwise(src, dst)}
    assert mapping == {0: 1, 1: 0}


def test_pairwise_is_deterministic():
    src, dst = _formation("a", _row(20, 0.0)), _formation("b", _row(20, 25.0))
    first = [(a.droneId, a.toPointId) for a in assign_pairwise(src, dst)]
    second = [(a.droneId, a.toPointId) for a in assign_pairwise(src, dst)]
    assert first == second


def test_cost_matrix_charges_for_a_role_change():
    a = np.array(_row(2, 0.0), dtype=np.float64)
    b = np.array(_row(2, 10.0), dtype=np.float64)
    weights = CostWeights()
    src = SceneAssignmentInputs(roleIds=["body", "body"])
    plain = build_cost_matrix(a, b, weights)
    changed = build_cost_matrix(
        a, b, weights, src=src, dst=SceneAssignmentInputs(roleIds=["wing", "wing"])
    )
    assert (changed >= plain).all()
    assert changed[0, 0] - plain[0, 0] == pytest.approx(weights.roleChangePenalty, abs=1e-6)


def test_cost_matrix_charges_less_for_moving_a_dark_drone():
    a = np.array(_row(2, 0.0), dtype=np.float64)
    b = np.array(_row(2, 30.0), dtype=np.float64)
    weights = CostWeights()
    lit = build_cost_matrix(a, b, weights, src=SceneAssignmentInputs(brightness=[1.0, 1.0]))
    dark = build_cost_matrix(a, b, weights, src=SceneAssignmentInputs(brightness=[0.0, 0.0]))
    assert dark[0, 0] < lit[0, 0]


def test_cost_matrix_protects_important_destinations_from_long_hauls():
    a = np.array([(0.0, 0.0, 40.0)], dtype=np.float64)
    b = np.array([(60.0, 0.0, 40.0)], dtype=np.float64)
    weights = CostWeights()
    cheap = build_cost_matrix(a, b, weights, dst=SceneAssignmentInputs(importance=[0.1]))
    dear = build_cost_matrix(a, b, weights, dst=SceneAssignmentInputs(importance=[1.0]))
    assert dear[0, 0] > cheap[0, 0]


def test_audience_view_only_affects_the_visual_term():
    a = np.array([(0.0, 0.0, 40.0)], dtype=np.float64)
    b = np.array([(30.0, 0.0, 40.0)], dtype=np.float64)
    weights = CostWeights()
    front = AudienceView(position=(0.0, 400.0, 20.0), lookAt=(15.0, 0.0, 40.0))
    away = AudienceView(position=(0.0, 400.0, 20.0), lookAt=(4000.0, 0.0, 40.0))
    assert build_cost_matrix(a, b, weights, view=front)[0, 0] > build_cost_matrix(
        a, b, weights, view=away
    )[0, 0]


# ------------------------------------------------------------ 10. lookahead


def test_lookahead_disabled_matches_plain_pairwise():
    scenes = [np.array(_row(10, y), dtype=np.float64) for y in (0.0, 30.0, 60.0)]
    mappings, diagnostics = assign_with_lookahead(scenes, horizon=1)
    for i, m in enumerate(mappings):
        expected = solve_matrix(build_cost_matrix(scenes[i], scenes[i + 1], CostWeights()))
        assert m == expected
    assert all(d.horizon == 1 for d in diagnostics)
    assert not any(d.lookaheadImproved for d in diagnostics)


def test_lookahead_horizon_is_clamped_to_three():
    scenes = [np.array(_row(6, y), dtype=np.float64) for y in (0.0, 20.0, 40.0, 60.0, 80.0)]
    _, diagnostics = assign_with_lookahead(scenes, horizon=9)
    assert all(d.horizon == 3 for d in diagnostics)


def test_lookahead_can_choose_a_different_intermediate_assignment():
    """A→B ties; B→C does not. The horizon should break the tie usefully."""
    a = np.array([(0.0, 0.0, 40.0), (40.0, 0.0, 40.0)], dtype=np.float64)
    b = np.array([(20.0, 20.0, 40.0), (20.0, -20.0, 40.0)], dtype=np.float64)
    c = np.array([(0.0, 40.0, 40.0), (40.0, -40.0, 40.0)], dtype=np.float64)
    flat, _ = assign_with_lookahead([a, b, c], horizon=1)
    ahead, diagnostics = assign_with_lookahead([a, b, c], horizon=3)
    assert flat[0] != ahead[0] or any(d.lookaheadImproved for d in diagnostics)


def test_lookahead_never_does_worse_than_the_baseline_it_replaces():
    """Compared against the same objective, not against a shorter horizon:
    the future term only exists once there is a horizon to charge it to."""
    rng = np.random.default_rng(4)
    scenes = [rng.uniform(-60.0, 60.0, size=(12, 3)) for _ in range(4)]
    for s in scenes:
        s[:, 2] = 45.0
    _, diagnostics = assign_with_lookahead(scenes, horizon=3)
    for d in diagnostics:
        assert d.totalCost <= d.baselineTotalCost + 1e-6
    assert chain_total_cost(diagnostics) > 0.0


def test_lookahead_is_deterministic():
    scenes = [np.array(_row(14, y), dtype=np.float64) for y in (0.0, 25.0, 50.0)]
    first, _ = assign_with_lookahead([s.copy() for s in scenes], horizon=3)
    second, _ = assign_with_lookahead([s.copy() for s in scenes], horizon=3)
    assert first == second


def test_diagnostics_break_the_total_into_its_terms():
    scenes = [np.array(_row(8, y), dtype=np.float64) for y in (0.0, 30.0, 60.0)]
    inputs = [
        SceneAssignmentInputs(roleIds=["body"] * 8, brightness=[1.0] * 8, importance=[0.8] * 8)
        for _ in scenes
    ]
    _, diagnostics = assign_with_lookahead(scenes, horizon=2, inputs=inputs)
    d = diagnostics[0]
    assert d.movementCost > 0.0
    assert d.totalCost == pytest.approx(
        d.movementCost + d.topologyCost + d.futureMovementCost + d.roleTransitionCost + d.visualDisruptionCost,
        rel=1e-6,
    )


def test_large_scene_falls_back_to_a_restricted_solve():
    """Above the exact-solver ceiling it must still return a permutation."""
    from app.choreography.assignment import MAX_EXACT

    n = MAX_EXACT + 40
    rng = np.random.default_rng(1)
    a = rng.uniform(-200.0, 200.0, size=(n, 3))
    b = rng.uniform(-200.0, 200.0, size=(n, 3))
    mapping = solve_matrix(build_cost_matrix(a, b, CostWeights()))
    assert len(mapping) == n
    assert len(set(mapping.values())) == n
