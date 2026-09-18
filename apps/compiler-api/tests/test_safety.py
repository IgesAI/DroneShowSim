from app.models import DroneAssignment, DroneProfile, Formation, FormationPoint, SafetyProfile
from app.safety.validate import validate_transition


def _line(fid: str, z: float) -> Formation:
    pts = [FormationPoint(id=i, position=(float(i) * 4.0, 0.0, z)) for i in range(6)]
    return Formation(id=fid, name=fid, sourceAssetId="x", points=pts)


def test_safe_parallel_shift():
    src, dst = _line("a", 10), _line("b", 20)
    assignment = [DroneAssignment(droneId=i, fromPointId=i, toPointId=i) for i in range(6)]
    report = validate_transition(src, dst, assignment, 8.0, DroneProfile(count=10), SafetyProfile())
    assert report.maxHorizontalVelocity.passed or report.recommendedDuration


def test_faster_closing_needs_more_room():
    from app.models import required_separation

    base = required_separation(DroneProfile(count=10), SafetyProfile(), 0.0)
    fast = required_separation(DroneProfile(count=10), SafetyProfile(), 16.0)
    assert fast > base + 1.0


def test_detects_close_pair():
    src = Formation(
        id="a",
        name="a",
        sourceAssetId="x",
        points=[FormationPoint(id=0, position=(0, 0, 10)), FormationPoint(id=1, position=(0.2, 0, 10))],
    )
    dst = Formation(
        id="b",
        name="b",
        sourceAssetId="x",
        points=[FormationPoint(id=0, position=(0, 0, 10)), FormationPoint(id=1, position=(0.2, 0, 10))],
    )
    assignment = [DroneAssignment(droneId=i, fromPointId=i, toPointId=i) for i in range(2)]
    report = validate_transition(src, dst, assignment, 2.0, DroneProfile(count=10, minimumSeparationM=2.5), SafetyProfile())
    assert report.minimumSeparation.passed is False
    assert report.passed is False
