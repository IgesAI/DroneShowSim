"""What an operator needs to know before letting an asset into a show.

Every number here is measured off the formation the compiler would actually
build, not off the artwork that was dropped in. The distinction matters: the
packer grows, relaxes and overflows artwork to seat the fleet at legal
spacing, so the drone figure can differ substantially from the drawing.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from app.models import DroneProfile, Formation, SafetyProfile, VenueConfiguration, required_separation

# Points the packer could not seat on the artwork and parked in a ring or a
# scatter instead. They are real drones in real airspace, but they are not
# drawing anything.
OVERFLOW_TYPES = {"halo", "spark", "fallback"}
# Above this a point is holding the shape rather than filling it in. Shared
# with the drone-budget readout in the editor.
STRUCTURAL_IMPORTANCE = 0.61
# The relax pass settles a few millimetres either side of its target, so an
# exact comparison against the packing margin reports a shortfall that is
# pure arithmetic. Anything inside this is not worth an operator's attention.
SPACING_TOLERANCE = 0.005


class ConversionReport(BaseModel):
    """Whether this asset became a formation worth flying."""

    pointCount: int = 0
    fleetCount: int = 0
    # Achieved vs the spacing formations must hold so the *morph* into the
    # next one stays legal. Falling short here is not a formation problem, it
    # is a transition problem that shows up later.
    minSeparationM: float = 0.0
    requiredSeparationM: float = 0.0
    # The separation two aircraft must never breach. The margin above is a
    # design target; this is the actual floor, and missing the two is the
    # difference between a longer transition and a violation.
    hardMinimumM: float = 0.0
    spacingOk: bool = True
    safeSeparation: bool = True
    # How far the packer had to grow the drawing to seat the fleet. 1.0 means
    # the artwork was already roomy enough; large values mean the figure in
    # the sky is much bigger than the one that was drawn.
    packScale: float = 1.0
    # Height still poking through the cleared ceiling after the packer slid
    # the figure down as far as the floor allows.
    ceilingOvershootM: float = 0.0
    fitsAirspace: bool = True
    overflowCount: int = 0
    structuralCount: int = 0
    detailCount: int = 0
    # False when the artwork carries no per-feature importance, which is the
    # normal case for a plain drawing. Splitting a budget into structural and
    # detail then reports every drone as detail, which reads like a problem
    # and is really just an absence of authoring.
    authoredImportance: bool = False
    widthM: float = 0.0
    depthM: float = 0.0
    heightM: float = 0.0
    lowestZ: float = 0.0
    highestZ: float = 0.0
    notes: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.spacingOk and self.fitsAirspace and self.overflowCount == 0


def conversion_report(
    formation: Formation,
    profile: DroneProfile,
    safety: SafetyProfile,
    venue: VenueConfiguration,
    required_spacing: float,
) -> ConversionReport:
    points = formation.points
    hard_minimum = required_separation(profile, safety)
    if not points:
        return ConversionReport(
            fleetCount=profile.count,
            requiredSeparationM=round(required_spacing, 4),
            hardMinimumM=round(hard_minimum, 4),
            notes=["the sampler found nothing to place; check the artwork has strokes or geometry"],
        )

    pts = np.array([p.position for p in points], dtype=np.float64)
    if len(pts) > 1:
        d, _ = cKDTree(pts).query(pts, k=2)
        min_sep = float(d[:, 1].min())
    else:
        min_sep = float("inf")

    overflow = sum(1 for p in points if (p.featureType or "") in OVERFLOW_TYPES)
    structural = sum(1 for p in points if p.importance >= STRUCTURAL_IMPORTANCE)
    on_shape = [p for p in points if (p.featureType or "") not in OVERFLOW_TYPES]
    authored = len({round(p.importance, 3) for p in on_shape}) > 1
    settings = formation.generationSettings
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    ceiling = venue.groundZ + venue.maxAltitudeM
    overshoot = float(getattr(settings, "ceilingOvershootM", 0.0) or 0.0)

    notes: list[str] = []
    spacing_ok = min_sep + SPACING_TOLERANCE >= required_spacing
    safe = min_sep + 1e-6 >= hard_minimum
    if not safe:
        notes.append(
            f"points sit {min_sep:.2f} m apart, inside the {hard_minimum:.2f} m two aircraft must "
            "never breach; this formation cannot fly as it stands"
        )
    elif not spacing_ok:
        short_cm = (required_spacing - min_sep) * 100
        notes.append(
            f"points sit {short_cm:.0f} cm short of the {required_spacing:.2f} m a morph needs; the "
            "transition into or out of this formation may be flagged"
        )
    if overflow:
        notes.append(
            f"{overflow} drones could not be seated on the artwork and were parked off-shape; "
            "give the figure more room, simplify it, or fly fewer drones"
        )
    if overshoot > 1e-6:
        notes.append(
            f"the figure stands {overshoot:.1f} m above the {venue.maxAltitudeM:.0f} m clearance "
            "even after being slid down as far as the floor allows"
        )
    scale = float(getattr(settings, "packScale", 1.0) or 1.0)
    if scale > 1.25:
        notes.append(
            f"the packer grew the drawing {scale:.2f}x to fit the fleet in at legal spacing, so the "
            "figure is larger than authored and transitions into it are longer"
        )

    return ConversionReport(
        pointCount=len(points),
        fleetCount=profile.count,
        minSeparationM=round(min_sep, 4) if np.isfinite(min_sep) else 0.0,
        requiredSeparationM=round(required_spacing, 4),
        hardMinimumM=round(hard_minimum, 4),
        spacingOk=spacing_ok,
        safeSeparation=safe,
        packScale=round(scale, 4),
        ceilingOvershootM=round(overshoot, 4),
        fitsAirspace=overshoot <= 1e-6 and float(hi[2]) <= ceiling + 1e-6,
        overflowCount=overflow,
        structuralCount=structural,
        detailCount=len(points) - structural,
        authoredImportance=authored,
        widthM=round(float(hi[0] - lo[0]), 3),
        depthM=round(float(hi[1] - lo[1]), 3),
        heightM=round(float(hi[2] - lo[2]), 3),
        lowestZ=round(float(lo[2]), 3),
        highestZ=round(float(hi[2]), 3),
        notes=notes,
    )
