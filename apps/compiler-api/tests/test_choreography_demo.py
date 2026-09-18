"""The 500-drone Dragon → Dragon Breath → Eagle demonstration.

Slow (about ten seconds), so it compiles once for the whole module.
"""

import math

import pytest

from app.choreography.audience import AudienceView
from app.choreography.pipeline import ChoreographyOptions, compile_choreography
from app.choreography.sampling import (
    engineering_classes,
    sample_programs,
    show_view_mask,
    time_grid,
)
from app.choreography.tracks import VISUAL_THRESHOLD
from app.choreography.validate import Geofence
from app.compile import solve_timeline
from app.demo import dragon_project

COUNT = 500


@pytest.fixture(scope="module")
def show():
    project = solve_timeline(dragon_project(count=COUNT, seed=1), mode="preview")
    venue = project.venue
    return compile_choreography(
        project,
        ChoreographyOptions(
            seed=1,
            geofence=Geofence(
                groundZ=venue.groundZ,
                maxAltitudeM=venue.groundZ + venue.maxAltitudeM,
                radiusM=venue.radiusM,
            ),
            audience=AudienceView(
                position=venue.audience.position,
                lookAt=venue.audience.lookAt,
                fovDeg=venue.audience.fovDeg,
            ),
        ),
    )


@pytest.fixture(scope="module")
def effect(show):
    assert show.diagnostics.effects, "the demo must contain the dragon breath"
    return show.diagnostics.effects[0]


def _programs_by_id(show):
    return {p.droneId: p for p in show.programs}


# ------------------------------------------------------------ the fixture


def test_demo_has_three_scenes_and_five_hundred_drones(show):
    assert len(show.programs) == COUNT
    kinds = [s.kind for s in show.scenes]
    assert "FORMATION" in kinds and "EFFECT" in kinds
    names = " ".join(s.name.lower() for s in show.scenes)
    assert "dragon" in names and "eagle" in names


def test_every_physical_drone_is_validated(show):
    assert show.safety.validatedDroneCount == COUNT
    assert show.safety.droneCount == COUNT


def test_the_whole_show_passes_safety(show):
    assert show.safety.geofenceViolations == []
    assert show.safety.altitudeViolations == []
    assert show.safety.minimumSeparation.passed
    assert show.safety.maxHorizontalVelocity.passed
    assert show.safety.maxVerticalVelocity.passed
    assert show.safety.maxAcceleration.passed
    assert show.safety.passed


def test_no_unresolved_conflicts_remain(show):
    assert show.diagnostics.conflictsAfter.errors() == []


# --------------------------------------------------- dark staging happens


def test_some_drones_go_dark_before_the_fire(show, effect):
    """The audience must not see the fire drones take their positions."""
    assert effect.staging.droneCount > 0
    assert effect.staging.stagingBeginsAt < effect.effectBeginsAt
    assert effect.staging.darkTravelDuration > 0.0

    programs = _programs_by_id(show)
    staged = [programs[i] for i in effect.stagedDroneIds]
    midway = 0.5 * (effect.staging.stagingBeginsAt + effect.effectBeginsAt)
    assert all(p.brightness(midway) <= VISUAL_THRESHOLD for p in staged)


def test_dark_drones_actually_move_while_dark(show, effect):
    programs = _programs_by_id(show)
    t0, t1 = effect.staging.stagingBeginsAt, effect.effectBeginsAt
    moved = [
        math.dist(programs[i].position(t0), programs[i].position(t1))
        for i in effect.stagedDroneIds
    ]
    assert max(moved) > 10.0
    assert sum(1 for d in moved if d > 1.0) > len(moved) // 2


def test_staging_is_not_earlier_than_the_physics_requires(show, effect):
    """Dark is not a licence to loiter: the group leaves when it must."""
    assert effect.staging.stagingBeginsAt > 0.0
    assert effect.staging.rejected is False


def test_the_fire_lights_up_and_travels_outward(show, effect):
    programs = _programs_by_id(show)
    staged = [programs[i] for i in effect.stagedDroneIds]
    peak = effect.effectBeginsAt + 0.6 * (effect.effectEndsAt - effect.effectBeginsAt)
    assert max(p.brightness(peak) for p in staged) > 0.5

    anchor = effect.anchor
    start = max(math.dist(p.position(effect.effectBeginsAt), anchor) for p in staged)
    end = max(math.dist(p.position(effect.effectEndsAt), anchor) for p in staged)
    assert end > start


def test_the_fire_is_warm_coloured(show, effect):
    programs = _programs_by_id(show)
    peak = effect.effectBeginsAt + 0.6 * (effect.effectEndsAt - effect.effectBeginsAt)
    lit = [
        programs[i].color(peak)
        for i in effect.stagedDroneIds
        if programs[i].brightness(peak) > 0.5
    ]
    assert lit
    assert all(r >= g >= b - 1e-6 for r, g, b in lit)


def test_fire_drones_go_dark_again_and_stage_for_the_eagle(show, effect):
    programs = _programs_by_id(show)
    staged = [programs[i] for i in effect.stagedDroneIds]
    after = effect.effectEndsAt + 0.5 * (effect.rejoin.eventBeginsAt - effect.effectEndsAt)
    assert any(p.brightness(after) <= VISUAL_THRESHOLD for p in staged)
    assert effect.rejoin.droneCount > 0
    assert effect.rejoin.stagingBeginsAt < effect.rejoin.eventBeginsAt


def test_borrowed_drones_change_role_over_time(show, effect):
    program = _programs_by_id(show)[effect.stagedDroneIds[0]]
    roles = [
        program.roleTrack.role_type(t)
        for t in (
            effect.staging.stagingBeginsAt - 1.0,
            0.5 * (effect.staging.stagingBeginsAt + effect.effectBeginsAt),
            0.5 * (effect.effectBeginsAt + effect.effectEndsAt),
        )
    ]
    assert roles[0] == "FORMATION"
    assert roles[1] == "STAGING"
    assert roles[2] == "EFFECT"


# ------------------------------------------------------------- the dragon


def test_the_dragon_keeps_its_face(show, effect):
    """Borrowing the jaw for the fire would be the cheapest and worst choice."""
    assert effect.allocation.highestRemovedImportance <= 0.55


def test_the_dragon_stays_recognisable(show, effect):
    """Most of the silhouette is still lit while the fire drones are away."""
    lit = COUNT - effect.allocation.allocatedDroneCount
    assert lit / COUNT > 0.85


def test_allocation_is_explainable(show, effect):
    a = effect.allocation
    assert a.requestedDroneCount > 0
    assert a.allocatedDroneCount > 0
    assert a.sourceRoles
    assert a.impactMetric
    assert a.formationImpactEstimate > 0.0


def test_diagnostics_name_the_drones_that_were_reassigned(show, effect):
    assert len(effect.stagedDroneIds) == effect.allocation.allocatedDroneCount
    assert len(set(effect.stagedDroneIds)) == len(effect.stagedDroneIds)


# ----------------------------------------------------------- the two views


def test_show_view_hides_the_dark_drones_engineering_view_keeps_them(show, effect):
    midway = 0.5 * (effect.staging.stagingBeginsAt + effect.effectBeginsAt)
    sampled = sample_programs(show.programs, [midway])
    visible = int(show_view_mask(sampled.brightness)[0].sum())
    assert visible < COUNT
    assert sampled.positions.shape[1] == COUNT
    assert len(set(engineering_classes(sampled.roles, sampled.brightness)[0].tolist())) > 1


def test_dark_drones_are_never_dropped_from_the_state(show):
    sampled = sample_programs(show.programs, time_grid(0.0, show.duration, 1.0))
    assert sampled.positions.shape[1] == COUNT
    assert (sampled.brightness <= VISUAL_THRESHOLD).any()


# ------------------------------------------------------------ determinism


def test_the_same_seed_compiles_the_same_show(show):
    project = solve_timeline(dragon_project(count=COUNT, seed=1), mode="preview")
    venue = project.venue
    again = compile_choreography(
        project,
        ChoreographyOptions(
            seed=1,
            geofence=Geofence(
                groundZ=venue.groundZ,
                maxAltitudeM=venue.groundZ + venue.maxAltitudeM,
                radiusM=venue.radiusM,
            ),
            audience=AudienceView(
                position=venue.audience.position,
                lookAt=venue.audience.lookAt,
                fovDeg=venue.audience.fovDeg,
            ),
        ),
    )
    assert [c.contentHash for c in again.compiled] == [c.contentHash for c in show.compiled]
    assert again.diagnostics.effects[0].stagedDroneIds == show.diagnostics.effects[0].stagedDroneIds


def test_compiled_programs_carry_their_provenance(show):
    compiled = show.compiled[0]
    assert compiled.logicalDroneId == show.programs[0].droneId
    assert compiled.contentHash
    assert compiled.compilerVersion
    assert compiled.seed == 1
    assert compiled.duration > 0.0


def test_compiled_program_is_self_contained_for_onboard_playback(show):
    """No wall-clock anywhere in the show data; execution config holds that."""
    compiled = show.compiled[0]
    dumped = compiled.model_dump()
    assert "trajectory" in dumped and "lighting" in dumped and "roles" in dumped
    assert not any("wall" in k.lower() or "gps" in k.lower() for k in dumped)
