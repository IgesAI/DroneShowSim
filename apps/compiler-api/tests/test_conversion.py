"""The asset -> drone-formation step, before any of it reaches a show."""

import numpy as np
import pytest
from scipy.spatial import cKDTree

from app.compile import artwork_formation, ensure_formations, morph_spacing
from app.demo import dragon_project
from app.formation.report import conversion_report
from app.main import formations_generate
from app.models import (
    Asset,
    DroneProfile,
    Formation,
    FormationGenerationSettings,
    GenerateFormationRequest,
    SafetyProfile,
    ShowProject,
    VenueConfiguration,
)

SQUARE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<path d="M10 10 H90 V90 H10 Z" stroke="#fff" fill="none" stroke-width="3"/>'
    "</svg>"
)


def _request(count: int = 60, **over) -> GenerateFormationRequest:
    body = {
        "assetId": "asset_sq",
        "name": "SQUARE",
        "content": SQUARE,
        "kind": "svg",
        "droneCount": count,
        "mode": "feature",
        "widthMeters": 80.0,
        "heightMeters": 40.0,
        "seed": 1,
        "droneProfile": DroneProfile(count=count).model_dump(),
        "safetyProfile": SafetyProfile().model_dump(),
        "venue": VenueConfiguration().model_dump(),
    }
    body.update(over)
    return GenerateFormationRequest.model_validate(body)


def _min_sep(formation: Formation) -> float:
    pts = np.array([p.position for p in formation.points], dtype=np.float64)
    d, _ = cKDTree(pts).query(pts, k=2)
    return float(d[:, 1].min())


def test_preview_places_every_drone_the_fleet_has():
    out = formations_generate(_request(count=60))
    assert out["pointCount"] == 60
    assert out["report"]["fleetCount"] == 60


def test_preview_is_the_same_formation_the_compiler_would_build():
    """The whole point of the step: approving the preview approves the show.

    These used to be two different calls with two different spacings, so the
    figure an operator signed off was denser than the one that flew.
    """
    count = 60
    settings = FormationGenerationSettings(mode="feature", widthM=80, heightM=40, seed=1)
    project = ShowProject(
        id="p",
        name="p",
        droneProfile=DroneProfile(count=count),
        assets=[Asset(id="asset_sq", name="SQUARE", kind="svg", content=SQUARE)],
        formations=[
            Formation(
                id="asset_sq",
                name="SQUARE",
                sourceAssetId="asset_sq",
                generationSettings=settings,
            )
        ],
    )
    compiled, _ = ensure_formations(project)
    previewed = formations_generate(
        _request(
            count=count,
            droneProfile=project.droneProfile.model_dump(),
            safetyProfile=project.safetyProfile.model_dump(),
            venue=project.venue.model_dump(),
        )
    )["formation"]

    built = compiled.formations[0]
    assert len(built.points) == len(previewed["points"])
    for a, b in zip(built.points, previewed["points"], strict=True):
        assert a.position == pytest.approx(tuple(b["position"]), abs=1e-9)
        assert a.importance == pytest.approx(b["importance"], abs=1e-9)


def test_preview_packs_for_the_morph_not_just_the_formation():
    """Formations must hold morph spacing, which is sqrt(2) x the raw minimum.

    Packing to the bare required separation looks fine standing still and
    violates the moment the show moves.
    """
    profile = DroneProfile(count=60)
    safety = SafetyProfile()
    out = formations_generate(_request(count=60))
    report = out["report"]
    assert report["requiredSeparationM"] == pytest.approx(morph_spacing(profile, safety), abs=1e-3)
    assert report["minSeparationM"] >= report["requiredSeparationM"] - 1e-6
    assert report["spacingOk"]


def test_preview_is_judged_against_the_venue_ceiling():
    """A figure taller than the clearance is reported, not quietly accepted."""
    low = VenueConfiguration(maxAltitudeM=12.0)
    out = formations_generate(_request(count=80, heightMeters=120.0, venue=low.model_dump()))
    report = out["report"]
    assert report["ceilingOvershootM"] > 0.0
    assert not report["fitsAirspace"]
    assert any("clearance" in n for n in report["notes"])


def test_report_counts_drones_parked_off_the_artwork():
    """Overflow drones are real aircraft that are not drawing anything."""
    profile = DroneProfile(count=400)
    safety = SafetyProfile()
    venue = VenueConfiguration()
    # A tiny frame cannot seat 400 drones on a square outline at morph spacing.
    formation = artwork_formation(
        formation_id="f",
        name="F",
        asset_id="a",
        content=SQUARE,
        kind="svg",
        settings=FormationGenerationSettings(mode="feature", widthM=10, heightM=10, seed=1),
        profile=profile,
        safety=safety,
        venue=venue,
    )
    report = conversion_report(formation, profile, safety, venue, morph_spacing(profile, safety))
    assert report.pointCount == 400
    assert report.overflowCount > 0
    assert any("could not be seated" in n for n in report.notes)


def test_report_splits_the_drone_budget_by_what_it_is_holding():
    out = formations_generate(_request(count=60))
    report = out["report"]
    assert report["structuralCount"] + report["detailCount"] == report["pointCount"]


def test_conversion_is_deterministic_for_one_seed():
    a = formations_generate(_request(count=60, seed=5))["formation"]
    b = formations_generate(_request(count=60, seed=5))["formation"]
    assert [p["position"] for p in a["points"]] == [p["position"] for p in b["points"]]


def test_retuning_size_changes_the_figure_not_the_drone_count():
    small = formations_generate(_request(count=60, widthMeters=40, heightMeters=20))
    large = formations_generate(_request(count=60, widthMeters=160, heightMeters=80))
    assert small["pointCount"] == large["pointCount"] == 60
    assert large["report"]["widthM"] > small["report"]["widthM"]


def test_bare_request_still_converts_without_a_project():
    """The endpoint stays usable on its own; it just assumes a default venue."""
    out = formations_generate(
        GenerateFormationRequest(
            assetId="a", name="A", content=SQUARE, kind="svg", droneCount=40
        )
    )
    assert out["pointCount"] == 40
    assert out["report"]["requiredSeparationM"] > 0


def test_demo_project_formations_still_report_clean():
    project, _ = ensure_formations(dragon_project(count=200, seed=1))
    profile, safety, venue = project.droneProfile, project.safetyProfile, project.venue
    for formation in project.formations:
        if formation.role == "launch":
            continue
        report = conversion_report(
            formation, profile, safety, venue, morph_spacing(profile, safety)
        )
        assert report.spacingOk, f"{formation.id}: {report.notes}"
        assert report.fitsAirspace, f"{formation.id}: {report.notes}"
        assert _min_sep(formation) == pytest.approx(report.minSeparationM, abs=1e-3)
