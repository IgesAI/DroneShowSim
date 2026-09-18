from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.models import DroneAssignment, Formation

# Assignment cost is squared distance, not distance, and this matters for
# safety rather than style. If no swap of two destinations lowers the sum of
# squared travel, then for every pair <a_i - a_j, b_i - b_j> >= 0, and a
# synchronised morph keeps them at least min(start, end) / sqrt(2) apart the
# whole way across. Plain distance gives no such bound: measured on a
# 500-drone morph it let two drones pass 0.05 m apart where squared distance
# held 2.78 m, for 8% more total travel.
MORPH_SEPARATION_BOUND = 2.0**0.5

# Deliberately tiny: the bound is min(start, end) / sqrt(2) only in whatever
# metric the cost is optimal for. Weighting one axis stretches that metric and
# loosens the guarantee by the square root of the weight, which on this show
# was the difference between 3.74 m and 3.22 m. This term is small enough to
# act as a tie-break and nothing more.
FEATURE_WEIGHT = 1e-3

# The bound above is a property of the *exact* solution and nothing weaker, so
# the only thing that should push a show onto the restricted solver is running
# out of memory. Measured, scipy matches 2500x2500 in 0.45 s and 4000x4000 in
# 1.4 s; the binding cost is the matrix itself at 8n² bytes, which is ~290 MB
# at 6000. The old ceiling of 900 was trading the guarantee for a fraction of
# a second, and at 1000 drones it put two of them through each other at
# 0.00 m on the way down to the pads.
MAX_EXACT_ASSIGNMENT = 6000


def morph_cost(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    sq = (diff * diff).sum(axis=2)
    n = sq.shape[0]
    feat = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :]) / max(n, 1)
    return sq + FEATURE_WEIGHT * feat * feat


def assign_formations(source: Formation, target: Formation) -> list[DroneAssignment]:
    a = np.array([p.position for p in source.points], dtype=np.float64)
    b = np.array([p.position for p in target.points], dtype=np.float64)
    n = min(len(a), len(b))
    a = a[:n]
    b = b[:n]
    cost = morph_cost(a, b)
    if n <= MAX_EXACT_ASSIGNMENT:
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
    """Restore the no-improving-swap property the separation bound rests on.

    Exact assignment already satisfies it, so this only does work for the
    restricted solver, and only within a window: it is a mitigation for shows
    too large to match exactly, not a substitute for having done so.
    """
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
                cur = _sq(pts_a[i], pts_b[bi]) + _sq(pts_a[j], pts_b[bj])
                alt = _sq(pts_a[i], pts_b[bj]) + _sq(pts_a[j], pts_b[bi])
                if alt + 1e-6 < cur:
                    dest[i], dest[j] = bj, bi
                    improved = True
    return [DroneAssignment(droneId=i, fromPointId=i, toPointId=dest[i]) for i in ids]


def _sq(p: np.ndarray, q: np.ndarray) -> float:
    d = p - q
    return float(d @ d)
