import time

from app.compile import solve_timeline
from app.demo import dragon_project
from app.safety.geometry import segment_distance, segment_distances
import numpy as np


def test_preview_faster_than_full():
    preview = dragon_project(count=40, seed=1)
    full = dragon_project(count=40, seed=1)
    t0 = time.perf_counter()
    solve_timeline(preview, mode="preview")
    preview_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    solve_timeline(full, mode="full")
    full_s = time.perf_counter() - t0
    assert preview_s < full_s
    assert preview_s < 2.5


def test_incremental_skips_unchanged_transitions():
    first = solve_timeline(dragon_project(count=40, seed=1), mode="preview")
    first.timeline.cues[1].holdDuration += 1.0
    t0 = time.perf_counter()
    second = solve_timeline(first, mode="preview")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.35
    assert len(second.timeline.transitions) == len(first.timeline.transitions)
    assert all(tr.assignment for tr in second.timeline.transitions)


def test_segment_distances_match_scalar():
    rng = np.random.default_rng(3)
    a0 = rng.normal(size=(12, 3))
    a1 = a0 + rng.normal(size=(12, 3)) * 0.4
    b0 = rng.normal(size=(12, 3))
    b1 = b0 + rng.normal(size=(12, 3)) * 0.4
    dist, s = segment_distances(a0, a1, b0, b1)
    for i in range(12):
        d, u = segment_distance(a0[i], a1[i], b0[i], b1[i])
        assert abs(d - dist[i]) < 1e-6
        assert abs(u - s[i]) < 1e-6
