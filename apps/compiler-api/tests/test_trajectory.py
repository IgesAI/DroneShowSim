import numpy as np

from app.trajectory.minjerk import evaluate, min_jerk


def test_endpoints_and_ease():
    p0 = np.array([0.0, 0.0, 0.0])
    p1 = np.array([10.0, 0.0, 0.0])
    assert np.allclose(evaluate(p0, p1, 0.0), p0)
    assert np.allclose(evaluate(p0, p1, 1.0), p1)
    assert min_jerk(0.0) == 0.0
    assert abs(min_jerk(1.0) - 1.0) < 1e-9
    assert 0.45 < min_jerk(0.5) < 0.55
