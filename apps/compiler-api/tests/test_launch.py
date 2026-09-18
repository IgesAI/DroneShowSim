import numpy as np

from app.compile import solve_timeline
from app.demo import cobra_project
from app.formation.launch import generate_launch_grid
from app.safety.geometry import segment_distance


def test_launch_grid_count_and_pitch():
    f, slots = generate_launch_grid(40, pitch=4.0)
    assert len(f.points) == 40
    assert len(slots) == 40
    xs = [p.position[0] for p in f.points]
    ys = [p.position[1] for p in f.points]
    zs = [p.position[2] for p in f.points]
    assert min(zs) < 0.2
    assert max(zs) < 0.2
    # nearest-neighbor ≈ pitch
    pts = np.array([p.position for p in f.points])
    d = []
    for i, p in enumerate(pts):
        others = np.linalg.norm(pts[np.arange(len(pts)) != i] - p, axis=1)
        d.append(others.min())
    assert abs(float(np.median(d)) - 4.0) < 0.05


def test_demo_starts_on_ground_and_lands():
    project = solve_timeline(cobra_project(count=20, seed=1))
    assert project.timeline.cues[0].phase == "takeoff"
    assert project.timeline.cues[-1].phase == "landing"
    launch = next(f for f in project.formations if f.role == "launch")
    assert all(p.position[2] < 1.0 for p in launch.points)
    assert project.showState in {"COMPILED", "VALIDATED"}


def test_crossing_segments_are_detected():
    a0 = np.array([-4.0, 0.0, 10.0])
    a1 = np.array([4.0, 0.0, 10.0])
    b0 = np.array([0.0, -4.0, 10.0])
    b1 = np.array([0.0, 4.0, 10.0])
    d, _ = segment_distance(a0, a1, b0, b1)
    assert d < 0.05
