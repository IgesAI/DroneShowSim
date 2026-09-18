from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.models import DroneAssignment, Formation


def assign_formations(source: Formation, target: Formation) -> list[DroneAssignment]:
    a = np.array([p.position for p in source.points], dtype=np.float64)
    b = np.array([p.position for p in target.points], dtype=np.float64)
    n = min(len(a), len(b))
    a = a[:n]
    b = b[:n]
    # cost = distance + vertical penalty + slight feature mismatch
    diff = a[:, None, :] - b[None, :, :]
    dist = np.linalg.norm(diff, axis=2)
    vert = np.abs(diff[:, :, 2])
    feat = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :]) / max(n, 1)
    cost = dist + 0.35 * vert + 0.05 * feat
    if n <= 900:
        rows, cols = linear_sum_assignment(cost)
        mapping = {int(r): int(c) for r, c in zip(rows, cols, strict=True)}
    else:
        mapping = _restricted(cost)
    return [
        DroneAssignment(droneId=i, fromPointId=i, toPointId=mapping.get(i, i % n))
        for i in range(n)
    ]


def _restricted(cost: np.ndarray) -> dict[int, int]:
    n = cost.shape[0]
    k = min(48, n)
    used = set()
    mapping: dict[int, int] = {}
    order = np.argsort(cost.min(axis=1))
    for i in order:
        i = int(i)
        candidates = np.argpartition(cost[i], k)[:k]
        ranked = sorted((float(cost[i, j]), int(j)) for j in candidates)
        for _, j in ranked:
            if j not in used:
                used.add(j)
                mapping[i] = j
                break
        if i not in mapping:
            leftover = next(j for j in range(n) if j not in used)
            used.add(leftover)
            mapping[i] = leftover
    return mapping


def swap_worst_crossings(
    source: Formation,
    target: Formation,
    assignment: list[DroneAssignment],
    limit: int = 80,
) -> list[DroneAssignment]:
    """Cheap conflict fix: swap destinations that cross and get closer after swap."""
    dest = {a.droneId: a.toPointId for a in assignment}
    pts_a = {p.id: np.array(p.position) for p in source.points}
    pts_b = {p.id: np.array(p.position) for p in target.points}
    ids = list(dest)
    improved = True
    rounds = 0
    while improved and rounds < 4:
        improved = False
        rounds += 1
        for idx, i in enumerate(ids[:limit]):
            for j in ids[idx + 1 : idx + 1 + limit]:
                bi, bj = dest[i], dest[j]
                cur = np.linalg.norm(pts_a[i] - pts_b[bi]) + np.linalg.norm(pts_a[j] - pts_b[bj])
                alt = np.linalg.norm(pts_a[i] - pts_b[bj]) + np.linalg.norm(pts_a[j] - pts_b[bi])
                if alt + 1e-6 < cur:
                    dest[i], dest[j] = bj, bi
                    improved = True
    return [DroneAssignment(droneId=i, fromPointId=i, toPointId=dest[i]) for i in ids]
