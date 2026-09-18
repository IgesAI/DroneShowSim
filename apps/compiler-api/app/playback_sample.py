from __future__ import annotations

import numpy as np

from app.animation.evaluate import apply_color, apply_motion, local_u
from app.models import ShowProject
from app.trajectory.segment import evaluate_segment


def sample_show(project: ShowProject, hz: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = project.droneProfile.count
    duration = max(project.timeline.duration, 0.1)
    frames = max(2, int(duration * hz) + 1)
    times = np.linspace(0.0, duration, frames)
    pos = np.zeros((frames, n, 3), dtype=np.float64)
    col = np.ones((frames, n, 3), dtype=np.float64) * 0.85
    formations = {f.id: f for f in project.formations}

    for fi, t in enumerate(times):
        placed = False
        for cue in project.timeline.cues:
            if cue.startTime <= t < cue.startTime + cue.holdDuration:
                f = formations[cue.formationId]
                pts = np.array([p.position for p in f.points[:n]], dtype=np.float64)
                anim = next(
                    (
                        a
                        for a in project.timeline.animations
                        if a.formationId == cue.formationId and local_u(a, float(t)) is not None
                    ),
                    None,
                )
                if anim is not None:
                    u = local_u(anim, float(t))
                    if u is not None:
                        pts = apply_motion(pts, anim, u)
                cols = np.array([pt.color for pt in f.points[:n]], dtype=np.float64)
                if anim is not None:
                    u = local_u(anim, float(t))
                    if u is not None:
                        cols = apply_color(cols, anim, u)
                for i, p in enumerate(pts):
                    pos[fi, i] = p
                    col[fi, i] = cols[i]
                placed = True
                break
        if placed:
            continue
        for tr in project.timeline.transitions:
            if tr.startTime <= t <= tr.startTime + tr.duration:
                src = formations[tr.fromFormationId]
                dst = formations[tr.toFormationId]
                u = (t - tr.startTime) / max(tr.duration, 1e-6)
                for a in tr.assignment:
                    if a.droneId >= n:
                        continue
                    p0 = np.array(src.points[a.fromPointId].position)
                    p1 = np.array(dst.points[a.toPointId].position)
                    pos[fi, a.droneId] = evaluate_segment(p0, p1, float(u), tr.type)
                    c0 = np.array(src.points[a.fromPointId].color)
                    c1 = np.array(dst.points[a.toPointId].color)
                    col[fi, a.droneId] = c0 + u * (c1 - c0)
                placed = True
                break
        if not placed and project.formations:
            f = project.formations[-1]
            for i, p in enumerate(f.points[:n]):
                pos[fi, i] = p.position
                col[fi, i] = p.color
    return times, pos, col
