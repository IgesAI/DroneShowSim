import numpy as np

from app.trajectory.segment import evaluate_segment, sample_transition


def test_styles_keep_endpoints():
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([10.0, 4.0, 8.0])
    for style in ("morph", "direct", "explode", "orbit", "wave", "umap"):
        p0 = evaluate_segment(a, b, 0.0, style)
        p1 = evaluate_segment(a, b, 1.0, style)
        assert np.allclose(p0, a, atol=1e-6)
        assert np.allclose(p1, b, atol=1e-6)


def test_explode_leaves_the_line():
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([10.0, 0.0, 0.0])
    mid = evaluate_segment(a, b, 0.5, "explode")
    line = evaluate_segment(a, b, 0.5, "morph")
    assert mid[2] > line[2] + 1.0


def test_batch_matches_scalar():
    p0 = np.array([[0.0, 0.0, 0.0], [2.0, 1.0, 0.0]])
    p1 = np.array([[8.0, 0.0, 4.0], [2.0, 7.0, 4.0]])
    u = np.array([0.0, 0.4, 1.0])
    batch = sample_transition(p0, p1, u, "orbit")
    for fi, ui in enumerate(u):
        for i in range(2):
            assert np.allclose(batch[fi, i], evaluate_segment(p0[i], p1[i], float(ui), "orbit"), atol=1e-6)
