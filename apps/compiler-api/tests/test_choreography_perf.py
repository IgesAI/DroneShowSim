"""Scale behaviour.

Conflict detection is the part that would go quadratic if nobody watched it,
so these assert on growth rather than on absolute seconds — wall-clock limits
make a test that fails on a loaded machine and passes on a fast one.
"""

import time

import numpy as np
import pytest

from app.choreography.conflict import detect_conflicts
from app.choreography.sampling import sample_programs, time_grid
from app.choreography.tracks import (
    DroneProgram,
    LightingKeyframe,
    LightingTrack,
    RoleSegment,
    RoleTrack,
    TrajectorySegment,
    TrajectoryTrack,
)
from app.models import DroneProfile, SafetyProfile

SIZES = (100, 500, 1000, 2500)


def _fleet(n: int, spacing: float = 8.0) -> list[DroneProgram]:
    """A grid that translates: dense enough to exercise the index, safe."""
    side = int(np.ceil(np.sqrt(n)))
    programs = []
    for i in range(n):
        x = (i % side) * spacing
        y = (i // side) * spacing
        programs.append(
            DroneProgram(
                droneId=i,
                trajectoryTrack=TrajectoryTrack(
                    segments=[
                        TrajectorySegment(
                            startTime=0.0,
                            duration=20.0,
                            start=(x, y, 40.0),
                            end=(x, y + 60.0, 55.0),
                        )
                    ]
                ),
                lightingTrack=LightingTrack(
                    keyframes=[LightingKeyframe(time=0.0, brightness=1.0 if i % 4 else 0.0)]
                ),
                roleTrack=RoleTrack(
                    segments=[
                        RoleSegment(
                            startTime=0.0,
                            endTime=20.0,
                            roleType="FORMATION" if i % 4 else "STAGING",
                        )
                    ]
                ),
            )
        )
    return programs


@pytest.mark.parametrize("n", SIZES)
def test_conflict_detection_runs_at_scale(n):
    programs = _fleet(n)
    graph = detect_conflicts(programs, DroneProfile(count=n), SafetyProfile(), end=20.0, hz=4.0)
    assert graph.passed
    assert graph.sampledFrames > 0
    # A full all-pairs sweep would be n(n-1)/2 per frame. Spatial indexing
    # must keep the examined pairs far below that.
    assert graph.checkedPairs < 0.05 * graph.sampledFrames * n * (n - 1) / 2


@pytest.mark.parametrize("n", SIZES)
def test_sampling_scales_linearly_in_drones(n):
    sampled = sample_programs(_fleet(n), time_grid(0.0, 20.0, 4.0))
    assert sampled.positions.shape == (sampled.frames, n, 3)
    assert sampled.brightness.shape == (sampled.frames, n)
    assert sampled.roles.shape == (sampled.frames, n)


def test_conflict_detection_is_sub_quadratic_in_fleet_size():
    """Twenty-five times the drones must not cost anything like 625 times."""

    def elapsed(n: int) -> float:
        programs = _fleet(n)
        t0 = time.perf_counter()
        detect_conflicts(programs, DroneProfile(count=n), SafetyProfile(), end=20.0, hz=4.0)
        return time.perf_counter() - t0

    small = max(elapsed(100), 1e-3)
    large = elapsed(2500)
    assert large / small < 60.0


def test_dark_drones_are_counted_in_the_checked_pairs():
    """Excluding them would make the check cheaper and the show unsafe."""
    n = 500
    programs = _fleet(n)
    lit_only = [p for p in programs if p.brightness(0.0) > 0.02]
    assert len(lit_only) < n
    full = detect_conflicts(programs, DroneProfile(count=n), SafetyProfile(), end=20.0, hz=4.0)
    partial = detect_conflicts(lit_only, DroneProfile(count=n), SafetyProfile(), end=20.0, hz=4.0)
    assert full.checkedPairs > partial.checkedPairs
