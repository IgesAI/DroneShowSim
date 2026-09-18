import numpy as np

from app.demo import DRAGON
from app.formation.sample import generate_formation
from app.models import FormationGenerationSettings


def test_svg_exactly_n_points():
    f = generate_formation(
        formation_id="f1",
        name="logo",
        asset_id="a1",
        content=DRAGON,
        kind="svg",
        count=80,
        settings=FormationGenerationSettings(seed=7, widthM=40, heightM=20, depthM=2),
        color=(1, 0, 0),
        min_sep_m=0.2,
    )
    assert len(f.points) == 80
    xs = [p.position[0] for p in f.points]
    zs = [p.position[2] for p in f.points]
    assert max(xs) - min(xs) <= 40 * 1.05
    assert max(zs) - min(zs) <= 20 * 1.2


def test_deterministic_seed():
    kwargs = dict(
        formation_id="f1",
        name="logo",
        asset_id="a1",
        content=DRAGON,
        kind="svg",
        count=40,
        settings=FormationGenerationSettings(seed=3),
        color=(1, 1, 1),
        min_sep_m=0.2,
    )
    a = generate_formation(**kwargs)
    b = generate_formation(**kwargs)
    assert [p.position for p in a.points] == [p.position for p in b.points]


def test_artwork_is_planar():
    f = generate_formation(
        formation_id="f1",
        name="logo",
        asset_id="a1",
        content=DRAGON,
        kind="svg",
        count=80,
        settings=FormationGenerationSettings(seed=7, widthM=40, heightM=20, depthM=0),
        color=(1, 0, 0),
        min_sep_m=0.2,
    )
    ys = [p.position[1] for p in f.points]
    assert max(ys) - min(ys) < 1e-6


def test_letter_a_apex_is_up():
    f = generate_formation(
        formation_id="a",
        name="A",
        asset_id="a",
        content="A",
        kind="text",
        count=30,
        settings=FormationGenerationSettings(seed=1, widthM=20, heightM=28, depthM=0),
        min_sep_m=0.35,
    )
    face = [p for p in f.points if p.importance >= 0.9] or f.points
    zs = [p.position[2] for p in face]
    xs = [p.position[0] for p in face]
    top = max(zs)
    apex = [p for p in face if p.position[2] >= top - (max(zs) - min(zs)) * 0.15]
    cx = (min(xs) + max(xs)) / 2
    apex_x = sum(p.position[0] for p in apex) / len(apex)
    assert abs(apex_x - cx) < (max(xs) - min(xs)) * 0.28


def test_line_samples_evenly():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20">
      <path d="M0 10 H 100" fill="none" stroke="#fff"/>
    </svg>"""
    f = generate_formation(
        formation_id="f",
        name="line",
        asset_id="a",
        content=svg,
        kind="svg",
        count=20,
        settings=FormationGenerationSettings(seed=1, widthM=40, heightM=10, depthM=0),
        color=(1, 1, 1),
        min_sep_m=0.15,
    )
    xs = sorted(p.position[0] for p in f.points)
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    assert min(gaps) > 0
    assert max(gaps) / min(gaps) < 1.2


def _min_pair(points) -> float:
    import numpy as np

    pts = np.array([p.position for p in points])
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    np.fill_diagonal(d2, np.inf)
    return float(np.sqrt(d2.min()))


def test_points_never_closer_than_min_sep():
    f = generate_formation(
        formation_id="text",
        name="SHOW",
        asset_id="t",
        content="SHOW",
        kind="text",
        count=80,
        settings=FormationGenerationSettings(seed=1, widthM=110, heightM=28, depthM=0),
        min_sep_m=3.7,
    )
    assert len(f.points) == 80
    assert _min_pair(f.points) >= 3.7 * 0.999


def test_tight_letter_scales_instead_of_halo():
    f = generate_formation(
        formation_id="a",
        name="A",
        asset_id="t",
        content="A",
        kind="text",
        count=60,
        settings=FormationGenerationSettings(seed=2, widthM=16, heightM=20, depthM=0),
        min_sep_m=3.7,
    )
    # `importance` now carries authored visual weight, so overflow is
    # identified by the feature the packer tagged it with instead.
    overflow = [p for p in f.points if p.featureType in {"halo", "spark"}]
    face = [p for p in f.points if p not in overflow]
    assert len(face) >= 50
    assert len(overflow) <= 10
    assert f.generationSettings.packScale > 1.05
    assert max(p.position[0] for p in face) - min(p.position[0] for p in face) > 20
    assert _min_pair(f.points) >= 3.7 * 0.999
    assert min(p.position[2] for p in f.points) >= 1.0


def test_in_flight_paths_and_flips_stay_above_ground():
    from app.animation.evaluate import apply_motion
    from app.models import AnimationClip
    from app.trajectory.segment import sample_transition

    p0 = np.array([[0.0, 0.0, 8.0], [4.0, -2.0, 12.0]])
    p1 = np.array([[2.0, 3.0, 6.0], [-1.0, 1.0, 9.0]])
    u = np.linspace(0, 1, 17)
    path = sample_transition(p0, p1, u, "morph")
    assert path[:, :, 2].min() >= 1.0

    buried = np.array([[0.0, 0.0, -4.0], [3.0, 1.0, -1.5]])
    clip = AnimationClip(
        id="a",
        name="flip",
        formationId="f",
        startTime=0,
        duration=4,
        motion="backflip",
        amplitude=1.0,
    )
    flipped = apply_motion(buried, clip, 0.35)
    assert flipped[:, 2].min() >= 1.0


def test_overflow_never_goes_underground():
    f = generate_formation(
        formation_id="text",
        name="SHOW",
        asset_id="t",
        content="SHOW",
        kind="text",
        count=80,
        settings=FormationGenerationSettings(seed=1, widthM=110, heightM=28, depthM=0),
        min_sep_m=3.7,
        ground_z=0.0,
    )
    assert min(p.position[2] for p in f.points) >= 1.0
