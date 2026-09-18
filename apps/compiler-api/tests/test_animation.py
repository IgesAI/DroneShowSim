import numpy as np

from app.animation.evaluate import apply_motion
from app.models import AnimationClip


def test_backflip_returns_home():
    pts = np.array([[10.0, 0.0, 20.0], [12.0, 2.0, 18.0], [8.0, -1.0, 22.0]])
    clip = AnimationClip(id="a", name="flip", formationId="f", motion="backflip", duration=4)
    out = apply_motion(pts, clip, 1.0)
    assert np.allclose(out, pts, atol=1e-6)
