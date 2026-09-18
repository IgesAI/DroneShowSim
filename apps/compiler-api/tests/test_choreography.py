"""Unit tests for the temporal choreography layer.

The invariant under test throughout: physical motion, visual appearance and
temporal role are independent. Safety reads the first and ignores the others.
"""

import math

import pytest

from app.choreography.allocation import (
    AllocationCandidate,
    allocate_effect_drones,
    match_to_targets,
)
from app.choreography.audience import AudienceView
from app.choreography.clock import (
    ExecutionState,
    ShowExecutionConfig,
    SimulationShowClock,
    TimeAxis,
)
from app.choreography.conflict import detect_conflicts, static_separation
from app.choreography.cost import (
    CostWeights,
    physical_motion_cost,
    role_change_cost,
    segment_visual_cost,
    visual_motion_cost,
)
from app.choreography.effects import EffectContext, build_effect
from app.choreography.sampling import (
    engineering_classes,
    sample_programs,
    show_view_mask,
    time_grid,
)
from app.choreography.scene import EffectSpec, ResourceRequest, Scene
from app.choreography.staging import (
    DarkStagingPlanner,
    StagingRequest,
    StagingVolume,
)
from app.choreography.tracks import (
    VISUAL_THRESHOLD,
    DroneProgram,
    LightingKeyframe,
    LightingTrack,
    RoleSegment,
    RoleTrack,
    TrajectorySegment,
    TrajectoryTrack,
)
from app.models import DroneProfile, SafetyProfile


def _profile(count: int = 10) -> DroneProfile:
    return DroneProfile(count=count)


def _flight(start, end, t0=0.0, dur=10.0) -> TrajectoryTrack:
    return TrajectoryTrack(
        segments=[TrajectorySegment(startTime=t0, duration=dur, start=start, end=end)]
    )


def _dark() -> LightingTrack:
    return LightingTrack(keyframes=[LightingKeyframe(time=0.0, brightness=0.0)]).normalize()


def _lit() -> LightingTrack:
    return LightingTrack(keyframes=[LightingKeyframe(time=0.0, brightness=1.0)]).normalize()


# --------------------------------------------------------------- 2. clock


def test_show_clock_starts_at_zero_and_is_monotonic():
    clock = SimulationShowClock()
    assert clock.now() == 0.0
    clock.advance(0.25)
    clock.advance(0.25)
    assert clock.now() == pytest.approx(0.5)


def test_time_axis_maps_external_clock_to_show_time():
    axis = TimeAxis(SimulationShowClock(), offset=100.0)
    assert axis.show_time(112.5) == pytest.approx(12.5)
    assert axis.external_time(12.5) == pytest.approx(112.5)
    assert axis.scene_time(12.5, scene_start=10.0) == pytest.approx(2.5)


def test_time_axis_supports_slowdown_without_touching_trajectories():
    axis = TimeAxis(SimulationShowClock(), offset=0.0, rate=0.5)
    assert axis.show_time(10.0) == pytest.approx(5.0)
    assert axis.normalized_scene_time(5.0, scene_start=0.0, scene_duration=10.0) == pytest.approx(0.5)


def test_paused_clock_stops_show_time():
    clock = SimulationShowClock()
    clock.advance(5.0)
    clock.pause()
    clock.advance(5.0)
    assert clock.now() == pytest.approx(5.0)
    clock.resume()
    clock.advance(1.0)
    assert clock.now() == pytest.approx(6.0)


def test_execution_config_is_separate_from_choreography():
    config = ShowExecutionConfig()
    assert config.state == "UNLOADED"
    assert config.scheduledStartTime is None


def test_execution_state_machine_rejects_illegal_transitions():
    config = ShowExecutionConfig()
    for target in ("LOADED", "READY", "AUTHORIZED", "WAITING", "RUNNING"):
        config = config.transition(target)
    assert config.state == "RUNNING"
    assert config.can_transition("SUSPENDED")
    with pytest.raises(ValueError):
        config.transition("READY")


def test_execution_state_is_not_a_pile_of_booleans():
    assert ExecutionState is not None
    config = ShowExecutionConfig()
    assert not any(isinstance(v, bool) for v in config.model_dump().values())


# ------------------------------------------------------- 4/5. roles, light


def test_role_changes_between_scenes():
    track = RoleTrack(
        segments=[
            RoleSegment(startTime=0.0, endTime=15.0, roleType="FORMATION", roleId="dragon_body"),
            RoleSegment(startTime=15.0, endTime=23.0, roleType="STAGING", roleId="dark_staging"),
            RoleSegment(startTime=23.0, endTime=31.0, roleType="EFFECT", roleId="fire"),
        ]
    ).normalize()
    assert track.role_type(1.0) == "FORMATION"
    assert track.role_type(18.0) == "STAGING"
    assert track.role_type(25.0) == "EFFECT"
    assert track.role_id(25.0) == "fire"


def test_role_and_brightness_are_independent():
    """A STAGING drone is usually dark, but nothing forces it to be."""
    program = DroneProgram(
        droneId=0,
        trajectoryTrack=_flight((0, 0, 20), (40, 0, 20)),
        lightingTrack=_lit(),
        roleTrack=RoleTrack(
            segments=[RoleSegment(startTime=0.0, endTime=10.0, roleType="STAGING")]
        ),
    )
    assert program.roleTrack.role_type(5.0) == "STAGING"
    assert program.brightness(5.0) == 1.0


def test_brightness_is_continuous_not_boolean():
    track = LightingTrack(
        keyframes=[
            LightingKeyframe(time=34.8, brightness=0.0),
            LightingKeyframe(time=35.2, brightness=1.0),
        ]
    ).normalize()
    assert track.brightness(35.0) == pytest.approx(0.5)
    assert 0.0 < track.brightness(34.9) < 1.0


def test_step_interpolation_holds_value():
    track = LightingTrack(
        keyframes=[
            LightingKeyframe(time=0.0, brightness=1.0, interpolation="step"),
            LightingKeyframe(time=10.0, brightness=0.0),
        ]
    ).normalize()
    assert track.brightness(9.99) == 1.0


def test_visual_activity_is_derived_from_brightness():
    track = LightingTrack(keyframes=[LightingKeyframe(time=0.0, brightness=VISUAL_THRESHOLD / 2)])
    assert track.is_visually_active(0.0) is False
    assert track.brightness(0.0) > 0.0


def test_changing_brightness_does_not_move_the_drone():
    program = DroneProgram(
        droneId=0,
        trajectoryTrack=_flight((0, 0, 20), (40, 0, 20)),
        lightingTrack=_lit(),
    )
    before = [program.position(t) for t in (0.0, 2.5, 5.0, 7.5, 10.0)]
    program.lightingTrack = _dark()
    assert [program.position(t) for t in (0.0, 2.5, 5.0, 7.5, 10.0)] == before


# -------------------------------------------------- 5/17. dark == physical


def test_dark_drone_is_still_checked_for_collisions():
    """The whole point: invisible is not absent."""
    profile, safety = _profile(), SafetyProfile()
    programs = [
        DroneProgram(droneId=0, trajectoryTrack=_flight((0, 0, 20), (0, 0, 20)), lightingTrack=_dark()),
        DroneProgram(droneId=1, trajectoryTrack=_flight((30, 0, 20), (0.4, 0, 20)), lightingTrack=_dark()),
    ]
    graph = detect_conflicts(programs, profile, safety, end=10.0)
    assert graph.passed is False
    assert any(c.severity == "error" for c in graph.conflicts)


def test_dark_and_lit_drones_are_checked_identically():
    profile, safety = _profile(), SafetyProfile()

    def graph_for(light):
        return detect_conflicts(
            [
                DroneProgram(droneId=0, trajectoryTrack=_flight((0, 0, 20), (0, 0, 20)), lightingTrack=light()),
                DroneProgram(droneId=1, trajectoryTrack=_flight((30, 0, 20), (0.4, 0, 20)), lightingTrack=light()),
            ],
            profile,
            safety,
            end=10.0,
        )

    assert graph_for(_dark).minimumSeparation == pytest.approx(graph_for(_lit).minimumSeparation)


def test_a_drone_may_move_while_dark():
    program = DroneProgram(
        droneId=0,
        trajectoryTrack=_flight((0, 0, 20), (60, 0, 20)),
        lightingTrack=_dark(),
        roleTrack=RoleTrack(segments=[RoleSegment(startTime=0.0, endTime=10.0, roleType="STAGING")]),
    )
    assert program.brightness(5.0) == 0.0
    assert math.dist(program.position(0.0), program.position(10.0)) == pytest.approx(60.0)


# ------------------------------------------------------ 16. trajectories


def test_trajectory_exposes_position_velocity_acceleration():
    seg = TrajectorySegment(startTime=0.0, duration=4.0, start=(0, 0, 0), end=(8, 0, 0))
    assert seg.position(0.0) == pytest.approx((0, 0, 0))
    assert seg.position(4.0)[0] == pytest.approx(8.0)
    assert seg.velocity(0.0) == pytest.approx((0, 0, 0))  # rest to rest
    assert seg.velocity(2.0)[0] > 0.0
    assert seg.acceleration(0.0) == pytest.approx((0, 0, 0))


def test_spline_segment_has_continuous_acceleration_at_knots():
    """C² is why the plume does not read as a jerk spike to the validator."""
    seg = TrajectorySegment(
        startTime=0.0,
        duration=6.0,
        start=(0, 0, 20),
        end=(30, 0, 20),
        waypoints=[(10, 4, 22), (20, -4, 18)],
        style="spline",
    )
    knot_t = 6.0 / 3.0
    before = seg.acceleration(knot_t - 1e-4)
    after = seg.acceleration(knot_t + 1e-4)
    assert before == pytest.approx(after, abs=1e-2)
    assert seg.acceleration(0.0) == pytest.approx((0, 0, 0), abs=1e-6)


def test_spline_passes_through_its_waypoints():
    seg = TrajectorySegment(
        startTime=0.0,
        duration=3.0,
        start=(0, 0, 10),
        end=(30, 0, 10),
        waypoints=[(10, 5, 10), (20, -5, 10)],
        style="spline",
    )
    assert seg.position(1.0) == pytest.approx((10, 5, 10), abs=1e-6)
    assert seg.position(2.0) == pytest.approx((20, -5, 10), abs=1e-6)


# --------------------------------------------------- 7/27. effect + seed


def _breath_spec(**kw) -> EffectSpec:
    return EffectSpec(
        id="fx", name="Breath", type="dragon-breath", duration=6.0, seed=7, **kw
    )


def test_effect_is_deterministic_for_the_same_seed():
    ctx = EffectContext(anchor=(0, 0, 60), droneCount=32, duration=6.0)
    a = build_effect(_breath_spec()).sample(0.4, ctx).positions()
    b = build_effect(_breath_spec()).sample(0.4, ctx).positions()
    assert a == b


def test_effect_differs_for_a_different_seed():
    ctx = EffectContext(anchor=(0, 0, 60), droneCount=32, duration=6.0)
    a = build_effect(_breath_spec()).sample(0.4, ctx).positions()
    b = build_effect(EffectSpec(id="fx", type="dragon-breath", duration=6.0, seed=99)).sample(0.4, ctx).positions()
    assert a != b


def test_effect_returns_the_requested_number_of_targets():
    ctx = EffectContext(anchor=(0, 0, 60), droneCount=48, duration=6.0)
    assert len(build_effect(_breath_spec()).sample(0.5, ctx).targets) == 48


def test_effect_arrives_dark_then_ignites_then_fades():
    """The drones are already on station before the audience sees anything."""
    ctx = EffectContext(anchor=(0, 0, 60), droneCount=24, duration=6.0)
    effect = build_effect(_breath_spec())

    def mean_brightness(u: float) -> float:
        targets = effect.sample(u, ctx).targets
        return sum(t.brightness for t in targets) / len(targets)

    assert mean_brightness(0.0) == 0.0
    assert mean_brightness(0.85) > mean_brightness(0.1)
    assert mean_brightness(1.0) < mean_brightness(0.85)


def test_effect_capacity_respects_internal_separation():
    ctx = EffectContext(anchor=(0, 0, 60), droneCount=400, duration=6.0, minSeparationM=5.0)
    effect = build_effect(_breath_spec())
    capacity = effect.max_safe_count(ctx, 400)
    assert capacity < 400
    fitted = ctx.model_copy(update={"droneCount": capacity})
    assert effect.min_internal_separation(fitted) >= 5.0


# ------------------------------------------------------- 8. allocation


def _candidates(importances: list[float]) -> list[AllocationCandidate]:
    return [
        AllocationCandidate(droneId=i, position=(float(i) * 6.0, 0.0, 30.0), importance=imp)
        for i, imp in enumerate(importances)
    ]


def test_allocation_prefers_low_importance_at_equal_cost():
    """Two points the same distance away: take the one nobody will miss."""
    cands = [
        AllocationCandidate(droneId=0, position=(10.0, 0.0, 30.0), importance=1.0),
        AllocationCandidate(droneId=1, position=(-10.0, 0.0, 30.0), importance=0.1),
    ]
    result = allocate_effect_drones(
        "fx", ResourceRequest(preferred=1, minimum=1, maximum=1), cands, (0.0, 0.0, 30.0)
    )
    assert result.droneIds == [1]


def test_allocation_refuses_to_sell_the_dragons_eye():
    cands = _candidates([1.0] * 4 + [0.2] * 8)
    result = allocate_effect_drones(
        "fx", ResourceRequest(preferred=6, minimum=4, maximum=6), cands, (0.0, 0.0, 30.0)
    )
    assert result.diagnostics.highestRemovedImportance <= 0.55
    assert all(c.importance <= 0.55 for c in result.candidates)


def test_allocation_raises_the_ceiling_rather_than_failing_and_says_so():
    cands = _candidates([0.9] * 6)
    result = allocate_effect_drones(
        "fx", ResourceRequest(preferred=4, minimum=4, maximum=4), cands, (0.0, 0.0, 30.0)
    )
    assert result.diagnostics.allocatedDroneCount == 4
    assert result.diagnostics.importanceCeiling > 0.55
    assert "ceiling raised" in result.diagnostics.shortfallReason


def test_allocation_reports_shortfall_rather_than_inventing_drones():
    result = allocate_effect_drones(
        "fx", ResourceRequest(preferred=40, minimum=20, maximum=64), _candidates([0.2] * 5), (0.0, 0.0, 30.0)
    )
    assert result.diagnostics.satisfied is False
    assert result.diagnostics.allocatedDroneCount == 5
    assert result.diagnostics.shortfallReason


def test_allocation_diagnostics_name_the_source_roles():
    result = allocate_effect_drones(
        "fx", ResourceRequest(preferred=3, minimum=1, maximum=3), _candidates([0.2] * 6), (0.0, 0.0, 30.0)
    )
    assert result.diagnostics.sourceRoles == {"FORMATION": 3}
    assert result.diagnostics.requestedDroneCount == 3
    assert result.diagnostics.impactMetric == "summed-importance"


def test_allocation_is_deterministic():
    args = ("fx", ResourceRequest(preferred=5, minimum=1, maximum=5), _candidates([0.3] * 20), (0.0, 0.0, 30.0))
    assert allocate_effect_drones(*args).droneIds == allocate_effect_drones(*args).droneIds


def test_optimal_matching_beats_greedy_on_crossing_paths():
    """Squared cost is what buys the separation bound; check it un-crosses."""
    cands = [
        AllocationCandidate(droneId=0, position=(0.0, 0.0, 0.0)),
        AllocationCandidate(droneId=1, position=(10.0, 0.0, 0.0)),
    ]
    pairs = match_to_targets(cands, [(10.0, 5.0, 0.0), (0.0, 5.0, 0.0)])
    assert {c.droneId: i for c, i in pairs} == {0: 1, 1: 0}


# ------------------------------------------------- 11/12/13. dark staging


def _planner() -> DarkStagingPlanner:
    return DarkStagingPlanner(_profile(64), SafetyProfile())


def _staging_request(**kw) -> StagingRequest:
    base = dict(
        label="fx",
        requiredArrivalTime=35.0,
        earliestStart=0.0,
        candidates=[
            AllocationCandidate(droneId=i, position=(float(i) * 8.0, 0.0, 40.0)) for i in range(6)
        ],
        targets=[(float(i) * 8.0, 60.0, 40.0) for i in range(6)],
        speedFactor=0.6,
    )
    base.update(kw)
    return StagingRequest(**base)


def test_staging_starts_late_but_early_enough():
    plan = _planner().plan(_staging_request())
    begins = plan.diagnostics.stagingBeginsAt
    assert 0.0 < begins < 35.0
    assert plan.diagnostics.darkTravelDuration >= max(
        a.window.requiredTravelTime for a in plan.assignments
    )


def test_staging_does_not_leave_earlier_than_it_needs_to():
    near = _planner().plan(_staging_request(targets=[(float(i) * 8.0, 4.0, 40.0) for i in range(6)]))
    far = _planner().plan(_staging_request(targets=[(float(i) * 8.0, 200.0, 40.0) for i in range(6)]))
    assert near.diagnostics.stagingBeginsAt > far.diagnostics.stagingBeginsAt


def test_staging_window_diagnostics_are_complete():
    window = _planner().plan(_staging_request()).assignments[0].window
    assert window.availableWindow[1] == 35.0
    assert window.requiredTravelTime > 0.0
    assert window.travelDistanceM > 0.0
    assert window.maximumVelocity > 0.0
    assert window.maximumAcceleration > 0.0


def test_unsafe_dark_staging_is_rejected_not_flown():
    """Six drones onto one point is not a plan, and the planner must say so."""
    plan = _planner().plan(_staging_request(targets=[(0.0, 60.0, 40.0)] * 6))
    assert plan.diagnostics.rejected is True
    assert plan.diagnostics.minimumPredictedSeparation < plan.diagnostics.requiredSeparation


def test_staging_respects_velocity_limits():
    plan = _planner().plan(_staging_request(requiredArrivalTime=35.0, earliestStart=0.0))
    profile = _profile()
    assert plan.diagnostics.maximumStagingVelocity <= profile.maxHorizontalSpeedMps + 1e-6


def test_impossible_staging_window_is_flagged_infeasible():
    plan = _planner().plan(
        _staging_request(
            requiredArrivalTime=1.0,
            earliestStart=0.0,
            targets=[(float(i) * 8.0, 900.0, 40.0) for i in range(6)],
        )
    )
    assert plan.diagnostics.infeasibleDrones
    assert plan.diagnostics.rejected is True


def test_same_inputs_and_seed_produce_the_same_staging():
    a = _planner().plan(_staging_request())
    b = _planner().plan(_staging_request())
    assert [(x.droneId, x.toPosition, x.startTime) for x in a.assignments] == [
        (x.droneId, x.toPosition, x.startTime) for x in b.assignments
    ]


def test_staging_volume_clamps_targets_into_its_bounds():
    volume = StagingVolume(id="box", shape="BOX", center=(0.0, 0.0, 40.0), bounds=(50.0, 50.0, 10.0))
    plan = _planner().plan(
        _staging_request(targets=[(float(i) * 8.0, 400.0, 40.0) for i in range(6)], volumes=[volume])
    )
    assert all(volume.contains(a.toPosition) for a in plan.assignments)
    assert all(a.volumeId == "box" for a in plan.assignments)


def test_sphere_volume_clamps_to_its_radius():
    volume = StagingVolume(id="s", shape="SPHERE", center=(0.0, 0.0, 40.0), bounds=(10.0, 0.0, 0.0))
    assert volume.contains((0.0, 0.0, 45.0))
    assert not volume.contains((0.0, 0.0, 60.0))
    assert math.dist(volume.clamp((0.0, 0.0, 60.0)), (0.0, 0.0, 40.0)) == pytest.approx(10.0)


def test_plane_offset_volume_keeps_drones_behind_the_plane():
    volume = StagingVolume(
        id="p", shape="PLANE_OFFSET", center=(0.0, -10.0, 0.0), normal=(0.0, -1.0, 0.0)
    )
    assert volume.contains((0.0, -30.0, 40.0))
    assert not volume.contains((0.0, 20.0, 40.0))
    assert volume.clamp((0.0, 20.0, 40.0))[1] == pytest.approx(-10.0)


def test_corridor_routes_the_group_behind_the_formation():
    """A rigid translation cannot change any separation within the group."""
    request = _staging_request(corridorShift=(0.0, -20.0, 0.0))
    plan = _planner().plan(request)
    for assignment in plan.assignments:
        assert assignment.waypoints
        assert min(p[1] for p in assignment.waypoints) <= -20.0 + 1e-6
        assert assignment.style == "spline"


def test_corridor_preserves_group_separation():
    direct = _planner().plan(_staging_request())
    routed = _planner().plan(_staging_request(corridorShift=(0.0, -20.0, 0.0)))
    assert routed.diagnostics.minimumPredictedSeparation >= direct.diagnostics.requiredSeparation


# --------------------------------------------- 14/15. audience + visual cost


def test_audience_projection_flattens_depth_but_geometry_does_not():
    """Two points 80 m apart in depth land on the same pixel. Only one of
    those facts is allowed to reach the collision checker."""
    view = AudienceView(position=(0.0, 500.0, 20.0), lookAt=(0.0, 0.0, 60.0))
    near = view.project_to_audience((0.0, 0.0, 60.0))
    far = view.project_to_audience((0.0, -80.0, 60.0))
    assert view.angular_separation((0.0, 0.0, 60.0), (0.0, -80.0, 60.0)) < 0.05
    assert math.dist(near, far) < 0.05
    assert math.dist((0.0, 0.0, 60.0), (0.0, -80.0, 60.0)) == pytest.approx(80.0)


def test_behind_offset_moves_away_from_the_audience():
    view = AudienceView(position=(0.0, 500.0, 20.0), lookAt=(0.0, 0.0, 20.0))
    assert view.behind_offset((0.0, 0.0, 20.0), 10.0)[1] == pytest.approx(-10.0)


def test_dark_motion_costs_almost_nothing_visually():
    lit = visual_motion_cost(40.0, 1.0, 1.0, 1.0)
    dark = visual_motion_cost(40.0, 0.0, 1.0, 1.0)
    assert lit > 0.0
    assert dark == 0.0


def test_dark_motion_costs_exactly_the_same_physically():
    a, b = (0.0, 0.0, 20.0), (40.0, 0.0, 20.0)
    assert physical_motion_cost(a, b) == pytest.approx(40.0)
    assert segment_visual_cost(a, b, brightness=0.0, importance=1.0) == 0.0
    assert segment_visual_cost(a, b, brightness=1.0, importance=1.0) > 0.0


def test_visual_cost_scales_with_feature_importance():
    assert visual_motion_cost(10.0, 1.0, 1.0, 1.0) > visual_motion_cost(10.0, 1.0, 0.2, 1.0)


def test_role_change_is_only_charged_when_the_role_changes():
    weights = CostWeights()
    assert role_change_cost("dragon_body", "dragon_body", weights) == 0.0
    assert role_change_cost("dragon_body", "fire", weights) == weights.roleChangePenalty


# ------------------------------------------------------ 20. view modes


def _two_programs() -> list[DroneProgram]:
    return [
        DroneProgram(
            droneId=0,
            trajectoryTrack=_flight((0, 0, 20), (10, 0, 20)),
            lightingTrack=_lit(),
            roleTrack=RoleTrack(segments=[RoleSegment(startTime=0.0, endTime=10.0, roleType="FORMATION")]),
        ),
        DroneProgram(
            droneId=1,
            trajectoryTrack=_flight((40, 0, 20), (50, 0, 20)),
            lightingTrack=_dark(),
            roleTrack=RoleTrack(segments=[RoleSegment(startTime=0.0, endTime=10.0, roleType="STAGING")]),
        ),
    ]


def test_show_view_hides_dark_drones():
    sampled = sample_programs(_two_programs(), time_grid(0.0, 10.0, 4.0))
    mask = show_view_mask(sampled.brightness)
    assert mask[:, 0].all()
    assert not mask[:, 1].any()


def test_engineering_view_contains_every_drone():
    programs = _two_programs()
    sampled = sample_programs(programs, time_grid(0.0, 10.0, 4.0))
    assert sampled.positions.shape[1] == len(programs)
    classes = engineering_classes(sampled.roles, sampled.brightness)
    assert classes.shape == sampled.brightness.shape
    assert len(set(classes[0].tolist())) == 2  # lit formation vs dark staging


def test_dark_drones_stay_in_the_sampled_state():
    sampled = sample_programs(_two_programs(), time_grid(0.0, 10.0, 4.0))
    assert sampled.positions[-1, 1][0] == pytest.approx(50.0)


# --------------------------------------------------------- 3. scene model


def test_scene_holds_intent_not_trajectories():
    scene = Scene(id="s", name="Dragon", kind="FORMATION", startTime=10.0, duration=20.0)
    assert scene.endTime == 30.0
    assert scene.contains(15.0)
    assert not scene.contains(31.0)
    assert not hasattr(scene, "positions")


def test_effect_scene_hangs_off_its_host_formation():
    scene = Scene(id="fx", name="Fire", kind="EFFECT", hostFormationId="frm_dragon", hostOffsetS=12.0)
    assert scene.hostFormationId == "frm_dragon"
    assert scene.hostOffsetS == 12.0


def test_resource_request_clamps_to_what_the_geometry_holds():
    request = ResourceRequest(preferred=64, minimum=40, maximum=80).capped(50)
    assert (request.preferred, request.minimum, request.maximum) == (50, 40, 50)


def test_static_separation_ignores_lighting_entirely():
    profile, safety = _profile(), SafetyProfile()
    assert static_separation(profile, safety) == static_separation(profile, safety)
    assert static_separation(profile, safety, "takeoff") >= static_separation(profile, safety)
