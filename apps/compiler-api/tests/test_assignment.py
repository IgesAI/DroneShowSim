from app.models import Formation, FormationPoint
from app.transition.assign import assign_formations


def _formation(fid: str, pts: list[tuple[float, float, float]]) -> Formation:
    return Formation(
        id=fid,
        name=fid,
        sourceAssetId="x",
        points=[FormationPoint(id=i, position=p) for i, p in enumerate(pts)],
    )


def test_identity_assignment():
    pts = [(float(i), 0.0, 10.0) for i in range(12)]
    a = _formation("a", pts)
    b = _formation("b", pts)
    mapping = assign_formations(a, b)
    assert [m.toPointId for m in mapping] == list(range(12))


def test_translated_assignment():
    src = [(float(i), 0.0, 0.0) for i in range(8)]
    dst = [(float(i), 0.0, 5.0) for i in range(8)]
    mapping = assign_formations(_formation("a", src), _formation("b", dst))
    assert [m.toPointId for m in mapping] == list(range(8))
