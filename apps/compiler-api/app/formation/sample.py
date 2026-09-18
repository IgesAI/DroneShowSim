from __future__ import annotations

import hashlib
import math
import random

import numpy as np

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
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], float]]:
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
        out.append(((x, y, z), s.color, s.importance))
    return out


def relax_planar(
    fitted: list[tuple[tuple[float, float, float], tuple[float, float, float], float]],
    iterations: int = 6,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], float]]:
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

    out = []
    for i, (_, color, imp) in enumerate(fitted):
        out.append(((float(pts[i, 0]), float(ys[i]), float(pts[i, 1])), color, imp))
    return out


Fitted = tuple[tuple[float, float, float], tuple[float, float, float], float]


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

    def accept(pos: tuple[float, float, float], color: tuple[float, float, float], imp: float) -> None:
        p = np.asarray(pos, dtype=np.float64)
        p[2] = max(float(p[2]), floor_z)
        for _ in range(16):
            if not occupied or float(np.min(np.linalg.norm(np.stack(occupied) - p, axis=1))) >= min_sep * 0.999:
                break
            p[1] -= min_sep * 0.4
            p[0] += float(rng.uniform(-min_sep * 0.25, min_sep * 0.25))
            p[2] = max(floor_z, float(p[2]) + float(rng.uniform(0.0, min_sep * 0.12)))
        occupied.append(p.copy())
        out.append(((float(p[0]), float(p[1]), float(p[2])), color, imp))

    for i in range(n_orbit):
        a = (2 * math.pi * i / max(n_orbit, 1)) + 0.18
        accept((c[0] + r * math.cos(a), y_back, cz + rz * math.sin(a)), (0.72, 0.84, 1.0), 0.45)
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
        )
    return out


def lift_above_floor(fitted: list[Fitted], floor_z: float = ART_FLOOR_Z) -> list[Fitted]:
    if not fitted:
        return fitted
    lo = min(p[0][2] for p in fitted)
    dz = 0.0 if lo >= floor_z else floor_z - lo
    return [((x, y, z + dz), col, imp) for (x, y, z), col, imp in fitted]


SAMPLER_VERSION = 4
MAX_SPAN_M = 400.0
MAX_SCALE = 12.0


def _span_m(pts: np.ndarray) -> float:
    return float(np.max(pts.max(axis=0) - pts.min(axis=0)))


def _max_span(n: int, min_sep: float) -> float:
    return max(MAX_SPAN_M, float(n) * min_sep * 0.85)


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


def pack_scaled(
    pts: np.ndarray,
    colors: list[tuple[float, float, float]],
    weights: np.ndarray,
    n: int,
    min_sep: float,
    author_span: float,
) -> tuple[list[Fitted], float, int]:
    centroid = pts.mean(axis=0)
    max_scale = min(MAX_SCALE, _max_span(n, min_sep) / max(author_span, 1.0))
    tiny = max(author_span * 0.002, 1e-4)
    picked = select_separated(pts, weights, n, tiny, require_n=False)
    if picked is None:
        return [], 1.0, n
    selected = pts[picked]
    dmin = _min_pair(selected)
    scale = 1.0 if dmin >= min_sep else min(max_scale, min_sep / max(dmin, 1e-9))
    q = (pts - centroid) * scale + centroid
    placed = q[picked]
    if _min_pair(placed) < min_sep * 0.999:
        picked = select_separated(q, weights, n, min_sep, require_n=False)
        if picked is None:
            return [], scale, n
        placed = q[picked]
    kept = [
        ((float(placed[i, 0]), float(placed[i, 1]), float(placed[i, 2])), colors[int(picked[i])], float(weights[int(picked[i])]))
        for i in range(len(picked))
    ]
    return kept, scale, n - len(kept)


def apply_capacity(fitted: list[Fitted], min_sep: float, seed: int, floor_z: float = ART_FLOOR_Z, count: int | None = None) -> list[Fitted]:
    pts = np.array([p[0] for p in fitted], dtype=np.float64)
    colors = [p[1] for p in fitted]
    weights = np.array([p[2] for p in fitted], dtype=np.float64)
    target = count if count is not None else len(fitted)
    kept, _scale, missing = pack_scaled(pts, colors, weights, target, min_sep, _span_m(pts))
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
        fitted = fit_volume(pts, colors, width, height, depth, z0)
        pts_f = np.array([p[0] for p in fitted], dtype=np.float64)
        author_span = max(width, height, depth, _span_m(pts_f))
        packed, scale, missing = pack_scaled(pts_f, colors, weights, count, min_sep, author_span)
    else:
        picked = sample_text_even(content, count) if kind == "text" else sample_svg_even(content, count)
        if len(picked) != count:
            rng = _rng(settings.seed, f"{asset_id}:{count}:{kind}")
            picked = farthest_point(picked, count, rng)
        fitted = fit_points(picked, width, height, depth, z0=z0)
        pts_f = np.array([p[0] for p in fitted], dtype=np.float64)
        colors = [p[1] for p in fitted]
        weights = np.full(len(fitted), 1.0)
        author_span = max(width, height, _span_m(pts_f))
        dmin = _min_pair(pts_f)
        max_scale = min(MAX_SCALE, _max_span(count, min_sep) / max(author_span, 1.0))
        scale = 1.0 if dmin >= min_sep else min(max_scale, min_sep / max(dmin, 1e-9))
        centroid = pts_f.mean(axis=0)
        q = (pts_f - centroid) * scale + centroid
        if _min_pair(q) < min_sep * 0.999:
            packed, scale, missing = pack_scaled(pts_f, colors, weights, count, min_sep, author_span)
        else:
            packed = [((float(q[i, 0]), float(q[i, 1]), float(q[i, 2])), colors[i], 1.0) for i in range(len(q))]
            missing = count - len(packed)
    extra = place_overflow(packed, missing, min_sep, settings.seed, floor_z=floor_z) if missing and packed else []
    if missing and not packed:
        extra = place_overflow(
            [((0.0, 0.0, floor_z + 8.0), (1.0, 0.85, 0.7), 1.0)],
            missing,
            min_sep,
            settings.seed,
            floor_z=floor_z,
        )
    fitted = lift_above_floor(packed + extra, floor_z)
    scaled = settings.model_copy(
        update={
            "widthM": width * scale,
            "heightM": height * scale,
            "depthM": depth * scale if depth > 1e-6 else depth,
            "samplerVersion": SAMPLER_VERSION,
            "packScale": scale,
        }
    )
    points = [
        FormationPoint(
            id=i,
            position=pos,
            color=color if color is not None else col,
            importance=imp,
            sourceFeatureId=i,
        )
        for i, (pos, col, imp) in enumerate(fitted)
    ]
    return Formation(
        id=formation_id,
        name=name,
        sourceAssetId=asset_id,
        points=points,
        transform=Transform(translation=(0.0, 0.0, 0.0)),
        generationSettings=scaled,
    )
