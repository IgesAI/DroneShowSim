from __future__ import annotations

import json

from app.models import ShowProject
from app.playback_sample import sample_show


def export_vviz(project: ShowProject, hz: float = 10.0) -> bytes:
    """VVIZ visualization interchange. NOT flight-ready."""
    times, pos, col = sample_show(project, hz)
    n = pos.shape[1]
    dt = 1.0 / hz
    performances = []
    for i in range(n):
        home = pos[0, i]
        # DSHOW → VVIZ: X right, Y up, Z into screen
        hx, hy, hz_ = float(home[0]), float(home[2]), float(-home[1])
        traversal = []
        prev = (hx, hy, hz_)
        for fi in range(len(times)):
            p = pos[fi, i]
            x, y, z = float(p[0]), float(p[2]), float(-p[1])
            traversal.append({"dt": dt, "dx": x - prev[0], "dy": y - prev[1], "dz": z - prev[2]})
            prev = (x, y, z)
        actions = []
        prev_c = None
        for fi in range(len(times)):
            c = col[fi, i]
            rgb = {"r": int(round(c[0] * 255)), "g": int(round(c[1] * 255)), "b": int(round(c[2] * 255))}
            if prev_c == rgb:
                if actions:
                    actions[-1]["frames"] = actions[-1].get("frames", 1) + 1
                continue
            actions.append(rgb)
            prev_c = rgb
        performances.append(
            {
                "id": i,
                "agentDescription": {
                    "homeX": hx,
                    "homeY": hy,
                    "homeZ": hz_,
                    "homeH": 0.0,
                    "agentTraversal": traversal,
                },
                "payloadDescription": [{"id": 0, "type": "Light", "payloadActions": actions}],
            }
        )
    doc = {
        "version": "1.0",
        "defaultPositionRate": hz,
        "defaultColorRate": hz,
        "timeOffsetSecs": 0.0,
        "luminaNote": "VVIZ visualization / interchange — NOT flight-ready",
        "coordinateSystemNote": "VVIZ X right, Y up, Z into screen; converted from DSHOW_LOCAL_RH",
        "performances": performances,
    }
    return json.dumps(doc).encode("utf-8")
