"""Demonstration fixture: dragon → dragon breath → eagle.

The artwork is generated as lofted contour rows rather than hand-drawn
outlines. A 500-drone fleet cannot sit on a one-dimensional outline at safe
spacing without inflating the show to kilometres, so the shapes are built as
evenly spaced surface rows from the start.
"""

from __future__ import annotations

import math

from app.choreography.scene import EffectSpec, ResourceRequest, Scene, SceneLighting
from app.models import (
    Asset,
    AudienceCamera,
    Cue,
    DroneProfile,
    Formation,
    FormationGenerationSettings,
    ShowProject,
    Timeline,
    VenueConfiguration,
)

Pt = tuple[float, float]


def _catmull(control: list[Pt], per_segment: int = 14) -> list[Pt]:
    pts = [control[0], *control, control[-1]]
    out: list[Pt] = []
    for i in range(len(pts) - 3):
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for k in range(per_segment):
            t = k / per_segment
            t2, t3 = t * t, t * t * t
            out.append(
                (
                    0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                    0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
                )
            )
    out.append(control[-1])
    return out


def _resample(curve: list[Pt], n: int) -> list[Pt]:
    lengths = [0.0]
    for a, b in zip(curve, curve[1:], strict=False):
        lengths.append(lengths[-1] + math.dist(a, b))
    total = lengths[-1] or 1.0
    out: list[Pt] = []
    j = 1
    for i in range(n):
        target = total * i / max(n - 1, 1)
        while j < len(lengths) - 1 and lengths[j] < target:
            j += 1
        span = max(lengths[j] - lengths[j - 1], 1e-9)
        t = (target - lengths[j - 1]) / span
        a, b = curve[j - 1], curve[j]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _offset(curve: list[Pt], widths: list[float], sign: float) -> list[Pt]:
    out: list[Pt] = []
    for i, (x, y) in enumerate(curve):
        a = curve[max(i - 1, 0)]
        b = curve[min(i + 1, len(curve) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        out.append((x - dy / n * widths[i] * sign, y + dx / n * widths[i] * sign))
    return out


def _profile(n: int, stops: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for i in range(n):
        t = i / max(n - 1, 1)
        value = stops[-1][1]
        for (t0, v0), (t1, v1) in zip(stops, stops[1:], strict=False):
            if t <= t1:
                u = 0.0 if t1 - t0 < 1e-9 else (t - t0) / (t1 - t0)
                value = v0 + (v1 - v0) * u
                break
        out.append(value)
    return out


def _bands(center: list[Pt], thickness: list[float], spacing: float) -> list[list[Pt]]:
    """Constant-offset contours through a tapered body.

    Lofting between the two edges collapses where the body is thin; fixed
    offsets keep every row the same distance apart and simply run out.
    """
    lanes = int(max(thickness) // spacing)
    out: list[list[Pt]] = []
    for k in range(-lanes, lanes + 1):
        offset = k * spacing
        run: list[Pt] = []
        for i, (x, y) in enumerate(center):
            if abs(offset) > thickness[i] + 1e-9:
                if len(run) >= 2:
                    out.append(run)
                run = []
                continue
            a = center[max(i - 1, 0)]
            b = center[min(i + 1, len(center) - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy) or 1.0
            run.append((x - dy / n * offset, y + dx / n * offset))
        if len(run) >= 2:
            out.append(run)
    return out


def _loft(edge_a: list[Pt], edge_b: list[Pt], rows: int) -> list[list[Pt]]:
    n = min(len(edge_a), len(edge_b))
    a, b = edge_a[:n], edge_b[:n]
    return [
        [
            (
                a[i][0] + (b[i][0] - a[i][0]) * (r / max(rows - 1, 1)),
                a[i][1] + (b[i][1] - a[i][1]) * (r / max(rows - 1, 1)),
            )
            for i in range(n)
        ]
        for r in range(rows)
    ]


def _path(points: list[Pt], color: str, width: float) -> str:
    d = " ".join(
        ("M" if i == 0 else "L") + f"{x:.2f} {y:.2f}" for i, (x, y) in enumerate(points)
    )
    return f'  <path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def _group(rows: list[str], feature: str, importance: float) -> str:
    """Declare what a part of the drawing is worth to the audience.

    The compiler borrows drones for effects from the least important
    features first, so the artwork has to say which parts those are. A wing
    tip missing is obvious; two drones out of the interior fill is not.
    """
    body = "\n".join(rows)
    return (
        f'  <g data-feature="{feature}" data-importance="{importance:.2f}">\n{body}\n  </g>'
    )


GRID = 6.0  # SVG units between neighbouring contour rows


def _dragon_svg() -> str:
    # Serpentine body: curled tail at the left, chest and shoulder to the
    # right, neck lifting the head clear of the wing. The curl is not
    # decoration — a 500-drone figure needs roughly 2700 units of drawing to
    # sit at safe spacing, and length spent on the tail reads better than the
    # same length spent thickening the torso into a slab.
    spine = _resample(
        _catmull(
            [
                (52, 142),
                (22, 138),
                (6, 124),
                (22, 110),
                (50, 116),
                (78, 112),
                (106, 104),
                (130, 92),
                (150, 76),
            ]
        ),
        96,
    )
    thickness = _profile(
        len(spine),
        [(0.0, 2.5), (0.2, 6.0), (0.42, 11.0), (0.68, 16.0), (0.88, 18.0), (1.0, 13.0)],
    )
    body = _bands(spine, thickness, GRID)

    neck = _resample(_catmull([(150, 74), (166, 60), (178, 44), (188, 34)]), 26)
    neck_bands = _bands(neck, _profile(len(neck), [(0.0, 9.0), (1.0, 5.5)]), GRID)

    # Wings are built as offset contours about a spar, not as lofts between a
    # root and a tip. A loft between two curves that meet at the shoulder
    # packs a dozen rows into a couple of units there, and the only thing the
    # packer can do with samples that close is discard them. Offset contours
    # are a fixed distance apart everywhere by construction and simply run out
    # where the wing gets thin.
    near_spar = _resample(_catmull([(140, 76), (112, 52), (80, 28), (46, 12), (24, 10)]), 56)
    near_wing = _bands(
        near_spar,
        _profile(len(near_spar), [(0.0, 5.0), (0.3, 26.0), (0.7, 34.0), (1.0, 10.0)]),
        GRID,
    )
    # The far wing reads as depth and pays for itself in drawing length.
    far_spar = _resample(_catmull([(148, 62), (120, 40), (92, 20), (68, 8)]), 36)
    far_wing = _bands(
        far_spar, _profile(len(far_spar), [(0.0, 4.0), (0.45, 13.0), (1.0, 5.0)]), GRID
    )

    # Dorsal ridge: spines standing off the back, the detail that says dragon
    # rather than lizard. Offset rather than crossing so it keeps its spacing.
    ridge = [
        _resample(
            [
                (spine[i][0] + 1.0, spine[i][1] - thickness[i] - 7.0)
                for i in range(12, len(spine) - 6)
            ],
            32,
        ),
        _resample(
            [
                (spine[i][0] + 1.0, spine[i][1] + thickness[i] + 7.0)
                for i in range(30, len(spine) - 8)
            ],
            22,
        ),
    ]

    head_spine = _resample(_catmull([(186, 33), (202, 27), (220, 25)]), 20)
    head = _bands(head_spine, _profile(20, [(0.0, 7.5), (0.55, 9.0), (1.0, 5.0)]), GRID)
    jaw = [
        _resample(_catmull([(202, 36), (220, 36), (234, 30)]), 10),
        _resample(_catmull([(206, 42), (220, 43), (230, 37)]), 8),
    ]
    horns = [
        _resample(_catmull([(188, 18), (178, 4)]), 6),
        _resample(_catmull([(199, 15), (202, 2)]), 6),
    ]
    legs = [
        _resample(_catmull([(96, 116), (88, 132), (104, 140)]), 11),
        _resample(_catmull([(140, 100), (134, 118), (150, 126)]), 11),
    ]

    # Lane 0 rides the authored contour and carries the silhouette; the inner
    # lanes are fill and are the first thing an effect should take.
    edge = [r for i, r in enumerate(body) if i in (0, len(body) - 1)]
    core = [r for i, r in enumerate(body) if i not in (0, len(body) - 1)]
    groups = [
        _group([_path(r, "#e88a1c", 4.0) for r in edge], "body-silhouette", 0.80),
        _group([_path(r, "#d97d16", 4.0) for r in core], "body-fill", 0.30),
        _group([_path(r, "#f2951b", 3.5) for r in neck_bands], "neck", 0.86),
        _group(
            [_path(r, "#ff9f1c", 3.5) for r in (near_wing[0], near_wing[-1])],
            "wing-edge",
            0.90,
        ),
        _group([_path(r, "#f0921a", 3.0) for r in near_wing[1:-1]], "wing-fill", 0.34),
        _group([_path(r, "#c96f12", 3.0) for r in far_wing], "far-wing", 0.28),
        _group([_path(r, "#ffb347", 3.0) for r in ridge], "dorsal-ridge", 0.62),
        _group([_path(r, "#ffd166", 3.5) for r in head], "head", 0.95),
        _group([_path(r, "#ffd166", 3.0) for r in jaw], "jaw", 0.96),
        _group([_path(r, "#ffb347", 3.0) for r in horns], "horn", 0.92),
        _group([_path(r, "#ffb347", 3.0) for r in legs], "leg", 0.64),
    ]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 145">\n'
        + "\n".join(groups)
        + "\n</svg>"
    )


def _eagle_svg() -> str:
    spine = _resample(_catmull([(120, 34), (120, 62), (120, 88), (120, 108)]), 44)
    thickness = _profile(len(spine), [(0.0, 7.0), (0.32, 16.0), (0.7, 14.0), (1.0, 8.0)])
    body = _bands(spine, thickness, GRID)

    def wing(sign: float) -> list[list[Pt]]:
        root = _resample(
            _catmull([(120 + sign * 18, 50), (120 + sign * 23, 70), (120 + sign * 19, 90)]), 36
        )
        tip = _resample(
            _catmull(
                [
                    (120 + sign * 44, 16),
                    (120 + sign * 80, 12),
                    (120 + sign * 108, 30),
                    (120 + sign * 118, 60),
                ]
            ),
            36,
        )
        return _loft(root, tip, 14)

    tail_root = _resample(_catmull([(108, 106), (120, 108), (132, 106)]), 14)
    tail_tip = _resample(_catmull([(96, 138), (120, 144), (144, 138)]), 14)
    tail = _loft(tail_root, tail_tip, 7)

    head_spine = _resample(_catmull([(120, 32), (120, 22)]), 8)
    head = _bands(head_spine, _profile(8, [(0.0, 9.0), (1.0, 6.0)]), GRID)
    beak = [_resample(_catmull([(126, 24), (140, 21), (126, 17)]), 6)]

    edge = [r for i, r in enumerate(body) if i in (0, len(body) - 1)]
    core = [r for i, r in enumerate(body) if i not in (0, len(body) - 1)]
    feathers = [row for side in (-1.0, 1.0) for row in wing(side)]
    groups = [
        _group([_path(r, "#eaf4ff", 4.0) for r in edge], "body-silhouette", 0.78),
        _group([_path(r, "#dcebfa", 4.0) for r in core], "body-fill", 0.34),
        _group([_path(r, "#cfe8ff", 3.5) for r in feathers[:6]], "wing-edge", 0.92),
        _group([_path(r, "#c2dff5", 3.5) for r in feathers[6:]], "wing-fill", 0.38),
        _group([_path(r, "#b9dcff", 3.0) for r in tail], "tail", 0.72),
        _group([_path(r, "#ffffff", 3.0) for r in head], "head", 0.95),
        _group([_path(r, "#ffffff", 3.0) for r in beak], "beak", 0.98),
    ]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 145">\n'
        + "\n".join(groups)
        + "\n</svg>"
    )


DRAGON = _dragon_svg()
EAGLE = _eagle_svg()


def dragon_breath_effect(seed: int = 7) -> EffectSpec:
    """Capacity request + anchor rule. No drone ids, no baked coordinates."""
    return EffectSpec(
        id="fx_dragon_breath",
        name="Dragon Breath",
        type="dragon-breath",
        resources=ResourceRequest(preferred=64, minimum=40, maximum=80),
        duration=8.0,
        seed=seed,
        anchorMode="formation-extreme",
        anchorFormationId="frm_dragon",
        anchorAxis=(1.0, 0.0, 0.25),
        anchorImportanceMin=0.61,
        anchorOffset=(6.0, 0.0, -2.0),
        maxStagingLeadS=16.0,
        blackoutLeadS=2.4,
        stagingMarginS=0.8,
        rejoinFadeS=0.8,
        parameters={
            "direction": [1.0, 0.0, 0.18],
            "coneAngleDeg": 28.0,
            "lengthM": 46.0,
            "spreadM": 10.0,
            "turbulenceSeed": 11,
            "turbulenceM": 2.4,
            "launchSpread": 0.4,
        },
    )


def dragon_project(count: int = 500, seed: int = 1) -> ShowProject:
    """Dragon → dragon breath → eagle.

    Nothing about fire is special-cased in the compiler: the effect requests
    capacity, is allocated low-importance dragon points, goes dark, moves to
    the mouth, ignites, then goes dark again to rejoin the eagle.
    """
    # Sized so the packed figure lands just under the venue ceiling: the art
    # is 240x145 units, so a 238 m frame puts the top of the tallest formation
    # near 144 m against a 150 m clearance.
    #
    # Both the figure and the clearance grow with the fleet, because points sit
    # along the strokes of the drawing rather than filling its area: the number
    # a figure can seat at a given spacing goes with stroke *length*, so it is
    # linear in the frame's scale, not quadratic. Doubling the fleet therefore
    # doubles the figure. Holding the frame fixed instead just saturates it —
    # at 1000 drones the packer grew the dragon to 240 m under a 150 m ceiling,
    # and once that growth is refused the surplus drones land in an overflow
    # halo that was never meant to hold hundreds. A show twice the size is
    # flown in a bigger cleared box; that is the variable that has to move.
    span = max(1.0, count / 500.0)
    art = FormationGenerationSettings(
        mode="feature", widthM=238 * span, heightM=144 * span, depthM=0, seed=seed
    )
    assets = [
        Asset(id="asset_dragon", name="Dragon", kind="svg", content=DRAGON),
        Asset(id="asset_eagle", name="Eagle", kind="svg", content=EAGLE),
    ]
    formations = [
        Formation(id="frm_dragon", name="DRAGON", sourceAssetId="asset_dragon", generationSettings=art),
        Formation(id="frm_eagle", name="EAGLE", sourceAssetId="asset_eagle", generationSettings=art),
    ]
    # The hold buys two things: a stretch where the audience simply sees a
    # dragon, and then the ~48 s the fire drones need to go dark and cross
    # behind the formation. Trim it and the compiler reports that staging had
    # to begin before the dragon had finished arriving.
    #
    # Dark travel is a distance, so it grows with the figure: the same crossing
    # that takes 48 s on the 500-drone dragon takes 141 s on the 2500-drone one.
    # The hold and the ignition offset scale with it, because a window that
    # cannot hold the crossing does not prevent the crossing — it just makes
    # the planner fly it faster, which is how this showed up in the first place
    # (10.9 m/s against an 8.0 limit).
    cues = [
        Cue(id="cue_dragon", formationId="frm_dragon", startTime=0, holdDuration=78 * span),
        Cue(id="cue_eagle", formationId="frm_eagle", startTime=0, holdDuration=14 * span),
    ]
    scenes = [
        Scene(id="scene_dragon", name="DRAGON", kind="FORMATION", formationIds=["frm_dragon"]),
        Scene(
            id="scene_dragon_fire",
            name="DRAGON BREATH",
            kind="EFFECT",
            hostFormationId="frm_dragon",
            hostOffsetS=60.0 * span,
            effects=[dragon_breath_effect(seed=7)],
            lighting=SceneLighting(mode="uniform", baseBrightness=1.0),
        ),
        Scene(id="scene_eagle", name="EAGLE", kind="FORMATION", formationIds=["frm_eagle"]),
    ]
    # Pads sit a full morph-safe spacing apart: the descent into the grid is a
    # contracting flow, so a tighter grid would squeeze drones together on the
    # way down no matter how the landing is assigned.
    profile = DroneProfile(count=count, launchPitchM=5.3)
    return ShowProject(
        id="show_dragon_demo",
        name="Dragon Demo",
        droneProfile=profile,
        venue=VenueConfiguration(
            maxAltitudeM=150.0 * span,
            radiusM=400.0 * span,
            audience=AudienceCamera(
                position=(0.0, 520.0 * span, 24.0),
                lookAt=(0.0, 0.0, 96.0 * span),
                distanceM=520.0 * span,
                fovDeg=52.0,
            ),
        ),
        assets=assets,
        formations=formations,
        timeline=Timeline(cues=cues),
        scenes=scenes,
    )
