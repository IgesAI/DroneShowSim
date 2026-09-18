from __future__ import annotations

import hashlib
import math
import random
from typing import NamedTuple

import numpy as np
from scipy.spatial import cKDTree

from app.geometry.mesh import MESH_KINDS, fit_volume, mesh_candidates
from app.geometry.svg import Sample, sample_svg_even, sample_text_even
from app.models import (
    DroneProfile,
    Formation,
    FormationGenerationSettings,
    FormationPoint,
    SafetyProfile,
    Transform,
    required_separation,
)


def _rng(seed: int, extra: str) -> random.Random:
    material = f"{seed}:{extra}".encode()
    digest = hashlib.sha256(material).hexdigest()
    return random.Random(int(digest[:16], 16))


def farthest_point(samples: list[Sample], n: int, rng: random.Random) -> list[Sample]:
    if len(samples) <= n:
        out = list(samples)
        while len(out) < n:
            s = rng.choice(samples)
            out.append(Sample(s.x + rng.uniform(-0.05, 0.05), s.y + rng.uniform(-0.05, 0.05), s.importance, s.color))
        return out
    weights = np.array([s.importance for s in samples], dtype=np.float64)
    start = int(np.argmax(weights))
    picked = [start]
    pts = np.array([[s.x, s.y] for s in samples], dtype=np.float64)
    min_d = np.sum((pts - pts[start]) ** 2, axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(min_d * (0.65 + 0.35 * weights / (weights.max() + 1e-9))))
        picked.append(nxt)
        d = np.sum((pts - pts[nxt]) ** 2, axis=1)
        min_d = np.minimum(min_d, d)
    return [samples[i] for i in picked]


def fit_points(
    samples: list[Sample],
    width: float,
    height: float,
    depth: float,
    z0: float,
) -> list["Fitted"]:
    xs = np.array([s.x for s in samples])
    ys = np.array([s.y for s in samples])
    bw = max(float(xs.max() - xs.min()), 1e-4)
    bh = max(float(ys.max() - ys.min()), 1e-4)
    scale = min(width / bw, height / bh) * 0.92
    cx, cy = float(xs.mean()), float(ys.mean())
    slab = min(max(depth, 0.0), 0.8)
    out = []
    for s in samples:
        # SVG y-down → DSHOW Z-up. Keep artwork planar so the audience silhouette is sharp.
        x = (s.x - cx) * scale
        z = -(s.y - cy) * scale + z0
        y = 0.0 if slab <= 1e-6 else (x / max(width, 1e-4)) * slab * 0.15
        out.append(
            Fitted(
                (x, y, z),
                s.color,
                weight=s.importance,
                importance=s.feature.importance,
                featureId=s.feature.id,
                featureType=s.feature.type,
            )
        )
    return out


def relax_planar(
    fitted: list["Fitted"],
    iterations: int = 6,
) -> list["Fitted"]:
    n = len(fitted)
    if n < 3:
        return fitted
    pts = np.array([[p[0][0], p[0][2]] for p in fitted], dtype=np.float64)
    home = pts.copy()
    ys = np.array([p[0][1] for p in fitted], dtype=np.float64)
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    np.fill_diagonal(d2, np.inf)
    nn = np.sqrt(d2.min(axis=1))
    median_nn = float(np.median(nn))
    if not np.isfinite(median_nn) or median_nn < 1e-6:
        return fitted
    thresh = median_nn * 0.55

    for _ in range(iterations):
        force = np.zeros_like(pts)
        d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
        np.fill_diagonal(d2, np.inf)
        close = d2 < (thresh * thresh)
        for i, j in zip(*np.nonzero(close), strict=False):
            if i >= j:
                continue
            vec = pts[i] - pts[j]
            dist = float(np.sqrt(d2[i, j]))
            if dist < 1e-6:
                push = np.array([thresh * 0.4, 0.0]) if (i + j) % 2 == 0 else np.array([0.0, thresh * 0.4])
            else:
                push = vec / dist * (thresh - dist) * 0.4
            force[i] += push
            force[j] -= push
        pts = 0.72 * (pts + force) + 0.28 * home

    return [
        item.moved((float(pts[i, 0]), float(ys[i]), float(pts[i, 1])))
        for i, item in enumerate(fitted)
    ]


class Fitted(NamedTuple):
    """One placed drone slot, carrying the authored feature it came from.

    `weight` is how much geometry detail sits here and drives which candidate
    points survive packing. `importance` is what the artwork says the point
    is worth to the audience and drives which drones an effect may borrow.
    The two are unrelated: a tight curve on an interior fill line is
    geometrically interesting and visually expendable.
    """

    position: tuple[float, float, float]
    color: tuple[float, float, float]
    weight: float
    importance: float = 0.6
    featureId: str = ""
    featureType: str = "silhouette"

    def moved(self, position: tuple[float, float, float]) -> "Fitted":
        return self._replace(position=position)


def default_min_sep() -> float:
    return required_separation(DroneProfile(), SafetyProfile())


def keep_separated(fitted: list[Fitted], min_sep: float) -> tuple[list[Fitted], list[Fitted]]:
    if min_sep <= 1e-6 or len(fitted) < 2:
        return list(fitted), []
    kept: list[Fitted] = []
    overflow: list[Fitted] = []
    acc: list[np.ndarray] = []
    for item in fitted:
        p = np.asarray(item[0], dtype=np.float64)
        if acc and float(np.linalg.norm(np.stack(acc) - p, axis=1).min()) < min_sep:
            overflow.append(item)
            continue
        kept.append(item)
        acc.append(p)
    if not kept and fitted:
        kept = [fitted[0]]
        overflow = list(fitted[1:])
    return kept, overflow


ART_FLOOR_Z = 1.0


def place_overflow(
    kept: list[Fitted],
    n: int,
    min_sep: float,
    seed: int,
    floor_z: float = ART_FLOOR_Z,
) -> list[Fitted]:
    if n <= 0:
        return []
    rng = np.random.default_rng(seed + 17)
    core = np.array([p[0] for p in kept], dtype=np.float64)
    c = core.mean(axis=0)
    span = np.maximum(core.max(axis=0) - core.min(axis=0), min_sep)
    n_orbit = (n + 1) // 2
    n_spark = n - n_orbit
    r = max(span[0] * 0.62, (n_orbit * min_sep / (2 * math.pi)) if n_orbit else min_sep)
    z_top = float(core[:, 2].max())
    z_bot = max(floor_z, float(core[:, 2].min()))
    cz = 0.5 * (z_top + z_bot)
    rz = min(max(0.5 * (z_top - z_bot), min_sep * 0.5), r * 0.28)
    if cz - rz < floor_z:
        cz = floor_z + rz
    y_back = float(c[1] - max(10.0, min_sep * 2.5))
    occupied = [np.asarray(p[0], dtype=np.float64) for p in kept]
    out: list[Fitted] = []

    def accept(
        pos: tuple[float, float, float],
        color: tuple[float, float, float],
        imp: float,
        feature: str,
    ) -> None:
        p = np.asarray(pos, dtype=np.float64)
        p[2] = max(float(p[2]), floor_z)
        for _ in range(16):
            if not occupied or float(np.min(np.linalg.norm(np.stack(occupied) - p, axis=1))) >= min_sep * 0.999:
                break
            p[1] -= min_sep * 0.4
            p[0] += float(rng.uniform(-min_sep * 0.25, min_sep * 0.25))
            p[2] = max(floor_z, float(p[2]) + float(rng.uniform(0.0, min_sep * 0.12)))
        occupied.append(p.copy())
        out.append(
            Fitted(
                (float(p[0]), float(p[1]), float(p[2])),
                color,
                weight=1.0,
                importance=imp,
                featureType=feature,
            )
        )

    for i in range(n_orbit):
        a = (2 * math.pi * i / max(n_orbit, 1)) + 0.18
        accept((c[0] + r * math.cos(a), y_back, cz + rz * math.sin(a)), (0.72, 0.84, 1.0), 0.45, "halo")
    spark_r = max(float(span[0]) * 0.55, min_sep * 3)
    for i in range(n_spark):
        u = (i + 0.5) / max(n_spark, 1)
        ang = i * 2.399963229728653
        rad = math.sqrt(u) * spark_r
        z = z_bot + (z_top - z_bot) * ((i * 0.618) % 1.0)
        accept(
            (c[0] + rad * math.cos(ang), y_back - min_sep * (0.45 + (i % 5) * 0.22), z),
            (1.0, 0.92, 0.68),
            0.28,
            "spark",
        )
    return out


def lift_above_floor(fitted: list[Fitted], floor_z: float = ART_FLOOR_Z) -> list[Fitted]:
    if not fitted:
        return fitted
    lo = min(p.position[2] for p in fitted)
    dz = 0.0 if lo >= floor_z else floor_z - lo
    if dz <= 0.0:
        return fitted
    return [p.moved((p.position[0], p.position[1], p.position[2] + dz)) for p in fitted]


def fit_between(
    fitted: list[Fitted], floor_z: float, ceiling_z: float | None
) -> tuple[list[Fitted], float]:
    """Slide the formation into the cleared airspace without reshaping it.

    Translation is the only move available here: it preserves every pairwise
    distance, so a formation that was packed to a safe spacing is still packed
    to a safe spacing afterwards. Squashing it to fit would not be, which is
    why a shape genuinely taller than the clearance is reported rather than
    quietly shrunk into a violation.
    """
    fitted = lift_above_floor(fitted, floor_z)
    if not fitted or ceiling_z is None:
        return fitted, 0.0
    hi = max(p.position[2] for p in fitted)
    if hi <= ceiling_z:
        return fitted, 0.0
    lo = min(p.position[2] for p in fitted)
    drop = min(hi - ceiling_z, max(lo - floor_z, 0.0))
    if drop > 1e-9:
        fitted = [
            p.moved((p.position[0], p.position[1], p.position[2] - drop)) for p in fitted
        ]
        hi -= drop
    return fitted, round(max(hi - ceiling_z, 0.0), 4)


SAMPLER_VERSION = 4
MAX_SPAN_M = 400.0
MAX_SCALE = 12.0


def _span_m(pts: np.ndarray) -> float:
    return float(np.max(pts.max(axis=0) - pts.min(axis=0)))


def _max_span(n: int, min_sep: float) -> float:
    return max(MAX_SPAN_M, float(n) * min_sep * 0.85)


def _envelope_scale(pts: np.ndarray, floor_z: float, ceiling_z: float | None) -> float:
    """The most the cleared airspace will let the figure grow.

    Growth happens about the centroid, so the vertical extent scales with it,
    and `fit_between` can only slide the result — never squash it. Without this
    cap the packer will happily grow a figure to seat every drone at legal
    spacing and hand back something taller than the airspace: on a 1000-drone
    dragon it produced a 240 m shape under a 150 m clearance, and the compiler
    then flew 24 aircraft above the ceiling to reach it.

    Refusing the growth instead sends the drones it cannot seat down the
    overflow path, which places them in a halo at legal spacing. A saturated
    figure with a visible halo is a design problem the operator can see and
    fix; an airspace breach is neither.
    """
    if ceiling_z is None or len(pts) < 2:
        return MAX_SCALE
    span = float(pts[:, 2].max() - pts[:, 2].min())
    if span <= 1e-6:
        return MAX_SCALE
    return max(1.0, (ceiling_z - floor_z) / span)


def select_separated(pts: np.ndarray, weights: np.ndarray, n: int, min_sep: float, require_n: bool = True) -> np.ndarray | None:
    if n <= 0 or len(pts) == 0:
        return None
    sep2 = min_sep * min_sep
    feat = np.where(weights >= 1.2)[0]
    feat = feat[np.argsort(-weights[feat])]
    kept: list[int] = []

    def far_enough(i: int) -> bool:
        if not kept:
            return True
        d2 = np.sum((pts[kept] - pts[i]) ** 2, axis=1)
        return float(d2.min()) >= sep2

    for i in feat:
        if far_enough(int(i)):
            kept.append(int(i))
            if len(kept) == n:
                return np.array(kept, dtype=np.int32)
    rest = np.array([i for i in range(len(pts)) if i not in set(kept)], dtype=np.int32)
    while len(kept) < n and len(rest):
        if not kept:
            pick = int(rest[int(np.argmax(weights[rest]))])
        else:
            d2 = ((pts[rest, None, :] - pts[np.array(kept)][None, :, :]) ** 2).sum(axis=2).min(axis=1)
            legal = d2 >= sep2
            if not np.any(legal):
                break
            legal_i = np.where(legal)[0]
            pick = int(rest[int(legal_i[np.argmax(d2[legal])])])
        kept.append(pick)
        rest = rest[rest != pick]
    if len(kept) < n and require_n:
        return None
    return np.array(kept, dtype=np.int32) if kept else None


def _min_pair(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return float("inf")
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    np.fill_diagonal(d2, np.inf)
    return float(np.sqrt(d2.min()))


def _robust_spacing(pts: np.ndarray, percentile: float = 2.0) -> float:
    """Typical neighbour distance, ignoring a few pathological pairs.

    Scaling the whole artwork by the single worst pair inflates a 500-drone
    show to kilometres. A low percentile keeps the show compact and leaves the
    handful of violators to the relaxation pass.
    """
    if len(pts) < 2:
        return float("inf")
    if len(pts) <= 12:
        return _min_pair(pts)
    d, _ = cKDTree(pts).query(pts, k=2)
    return float(np.percentile(d[:, 1], percentile))


def relax_separation(
    pts: np.ndarray,
    min_sep: float,
    iterations: int = 24,
    max_drift: float | None = None,
) -> np.ndarray:
    """Push crowded points apart in place instead of inflating the artwork.

    Drawings put their points on strokes, so a 500-drone silhouette can sit in
    a box with twice the area it needs and still violate spacing everywhere,
    because all the room is in the interior and all the points are on the
    outline. Scaling the whole figure to fix that makes a show that is mostly
    empty air and, on this demo, too tall for the cleared airspace.

    `max_drift` leashes each point to where the artwork put it, so crowded
    strokes thicken into bands using the space beside them while the silhouette
    stays where it was drawn.
    """
    out = pts.astype(np.float64).copy()
    anchors = out.copy()
    target = min_sep * 1.02
    for _ in range(iterations):
        pairs = cKDTree(out).query_pairs(target, output_type="ndarray")
        if len(pairs) == 0:
            break
        a, b = pairs[:, 0], pairs[:, 1]
        delta = out[a] - out[b]
        dist = np.maximum(np.linalg.norm(delta, axis=1), 1e-6)
        push = (((target - dist) / dist) * 0.5)[:, None] * delta
        shift = np.zeros_like(out)
        np.add.at(shift, a, push)
        np.add.at(shift, b, -push)
        out += shift
        if max_drift is not None:
            off = out - anchors
            far = np.linalg.norm(off, axis=1)
            over = far > max_drift
            if np.any(over):
                out[over] = anchors[over] + off[over] * (max_drift / far[over])[:, None]
    return out


RELAX_PASSES = 160


def _spread_scale(pts: np.ndarray, min_sep: float, max_scale: float) -> float:
    """How much the artwork must grow once relaxation has used the space it has.

    The naive answer, min_sep divided by the current neighbour distance,
    assumes points can only move if the whole drawing moves. They can move
    within it, so the figure only needs to grow by whatever the area itself
    cannot supply: the deficit between the footprint the drone count requires
    and the footprint the drawing already occupies.
    """
    if len(pts) < 2:
        return 1.0
    spacing = _robust_spacing(pts)
    if spacing >= min_sep:
        return 1.0
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    extent = np.sort(hi - lo)[-2:]  # the two axes the artwork actually uses
    available = float(extent[0] * extent[1])
    # Hexagonal packing is the densest arrangement of equal disks, so this is
    # the smallest footprint the count can legally occupy.
    required = len(pts) * min_sep * min_sep * 0.866
    by_area = math.sqrt(required / available) if available > 1e-6 else max_scale
    by_spacing = min_sep / max(spacing, 1e-9)
    return float(min(max_scale, max(1.0, min(by_spacing, by_area))))


def place_all(
    pts: np.ndarray, min_sep: float, max_scale: float, rounds: int = 20
) -> tuple[np.ndarray, float, bool]:
    """Seat every point at legal spacing, growing the figure only as needed.

    Relaxation alone cannot fix artwork whose strokes converge — a dozen loft
    rows meeting at a shoulder have no free space between them at any leash
    length. The alternative the packer used to reach for was discarding the
    points it could not seat, which on this dragon meant throwing away 337 of
    500 drones and scattering them in a halo. Growing the drawing 8% at a time
    keeps every drone on the artwork, and the caller can still refuse a result
    that no longer fits the venue.
    """
    centroid = pts.mean(axis=0)
    scale = _spread_scale(pts, min_sep, max_scale)
    for _ in range(rounds):
        q = (pts - centroid) * scale + centroid
        if _min_pair(q) < min_sep * 0.999:
            q = relax_separation(q, min_sep, iterations=RELAX_PASSES, max_drift=min_sep * 2.0)
        if _min_pair(q) >= min_sep * 0.999:
            return q, scale, True
        if scale >= max_scale - 1e-9:
            break
        # Small steps: every percent of growth is metres of airspace and
        # seconds of transit, and overshooting the smallest workable size is
        # what pushed this show's dragon through the ceiling.
        scale = min(max_scale, scale * 1.035)
    return q, scale, False


def pack_scaled(
    candidates: list[Fitted],
    weights: np.ndarray,
    n: int,
    min_sep: float,
    author_span: float,
    scale_ceiling: float = MAX_SCALE,
) -> tuple[list[Fitted], float, int]:
    pts = np.array([c.position for c in candidates], dtype=np.float64)
    centroid = pts.mean(axis=0)
    max_scale = min(MAX_SCALE, scale_ceiling, _max_span(n, min_sep) / max(author_span, 1.0))
    tiny = max(author_span * 0.002, 1e-4)
    picked = select_separated(pts, weights, n, tiny, require_n=False)
    if picked is None:
        return [], 1.0, n
    placed, scale, seated = place_all(pts[picked], min_sep, max_scale)
    if not seated:
        q = (pts - centroid) * scale + centroid
        picked = select_separated(q, weights, n, min_sep, require_n=False)
        if picked is None:
            return [], scale, n
        placed = q[picked]
    kept = [
        candidates[int(picked[i])].moved(
            (float(placed[i, 0]), float(placed[i, 1]), float(placed[i, 2]))
        )
        for i in range(len(picked))
    ]
    return kept, scale, n - len(kept)


def apply_capacity(fitted: list[Fitted], min_sep: float, seed: int, floor_z: float = ART_FLOOR_Z, count: int | None = None) -> list[Fitted]:
    pts = np.array([p.position for p in fitted], dtype=np.float64)
    weights = np.array([p.weight for p in fitted], dtype=np.float64)
    target = count if count is not None else len(fitted)
    kept, _scale, missing = pack_scaled(fitted, weights, target, min_sep, _span_m(pts))
    extra = place_overflow(kept, missing, min_sep, seed, floor_z=floor_z) if missing else []
    return lift_above_floor(kept + extra, floor_z)


def generate_formation(
    *,
    formation_id: str,
    name: str,
    asset_id: str,
    content: str,
    kind: str,
    count: int,
    settings: FormationGenerationSettings,
    color: tuple[float, float, float] | None = None,
    min_sep_m: float | None = None,
    ground_z: float = 0.0,
    ceiling_z: float | None = None,
) -> Formation:
    prior = max(float(settings.packScale or 1.0), 1.0)
    width = settings.widthM / prior
    height = settings.heightM / prior
    depth = settings.depthM / prior if settings.depthM > 1e-6 else settings.depthM
    z0 = height * 0.45 + 12.0
    min_sep = default_min_sep() if min_sep_m is None else min_sep_m
    floor_z = ground_z + ART_FLOOR_Z
    if kind in MESH_KINDS:
        pts, weights, colors = mesh_candidates(kind, content, count, settings.mode, settings.seed)
        raw = fit_volume(pts, colors, width, height, depth, z0)
        candidates = [
            Fitted(pos, col, weight=w, importance=imp, featureType="volume")
            for (pos, col, imp), w in zip(raw, weights, strict=False)
        ]
        pts_f = np.array([c.position for c in candidates], dtype=np.float64)
        author_span = max(width, height, depth, _span_m(pts_f))
        room = _envelope_scale(pts_f, floor_z, ceiling_z)
        packed, scale, missing = pack_scaled(
            candidates, weights, count, min_sep, author_span, room
        )
    else:
        picked = sample_text_even(content, count) if kind == "text" else sample_svg_even(content, count)
        if len(picked) != count:
            rng = _rng(settings.seed, f"{asset_id}:{count}:{kind}")
            picked = farthest_point(picked, count, rng)
        candidates = fit_points(picked, width, height, depth, z0=z0)
        pts_f = np.array([c.position for c in candidates], dtype=np.float64)
        weights = np.array([c.weight for c in candidates], dtype=np.float64)
        author_span = max(width, height, _span_m(pts_f))
        room = _envelope_scale(pts_f, floor_z, ceiling_z)
        max_scale = min(MAX_SCALE, room, _max_span(count, min_sep) / max(author_span, 1.0))
        q, scale, seated = place_all(pts_f, min_sep, max_scale)
        if not seated:
            packed, scale, missing = pack_scaled(
                candidates, weights, count, min_sep, author_span, room
            )
        else:
            packed = [
                c.moved((float(q[i, 0]), float(q[i, 1]), float(q[i, 2])))
                for i, c in enumerate(candidates)
            ]
            missing = count - len(packed)
    extra = place_overflow(packed, missing, min_sep, settings.seed, floor_z=floor_z) if missing and packed else []
    if missing and not packed:
        extra = place_overflow(
            [Fitted((0.0, 0.0, floor_z + 8.0), (1.0, 0.85, 0.7), 1.0, 0.6, "", "fallback")],
            missing,
            min_sep,
            settings.seed,
            floor_z=floor_z,
        )
    fitted, overshoot = fit_between(packed + extra, floor_z, ceiling_z)
    scaled = settings.model_copy(
        update={
            "widthM": width * scale,
            "heightM": height * scale,
            "depthM": depth * scale if depth > 1e-6 else depth,
            "samplerVersion": SAMPLER_VERSION,
            "packScale": scale,
            "ceilingOvershootM": overshoot,
        }
    )
    points = [
        FormationPoint(
            id=i,
            position=p.position,
            color=color if color is not None else p.color,
            importance=min(1.0, max(0.0, p.importance)),
            sourceFeatureId=i,
            featureId=p.featureId or None,
            featureType=p.featureType or None,
        )
        for i, p in enumerate(fitted)
    ]
    return Formation(
        id=formation_id,
        name=name,
        sourceAssetId=asset_id,
        points=points,
        transform=Transform(translation=(0.0, 0.0, 0.0)),
        generationSettings=scaled,
    )
