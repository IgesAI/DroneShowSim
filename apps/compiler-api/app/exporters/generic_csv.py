from __future__ import annotations

import io
import zipfile

from app.models import ShowProject
from app.playback_sample import sample_show


def export_generic_csv(project: ShowProject, hz: float = 25.0) -> bytes:
    times, pos, col = sample_show(project, hz)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        header = "time_s,drone_id,x_m,y_m,z_m,r,g,b\n"
        rows = [header]
        n = pos.shape[1]
        for fi, t in enumerate(times):
            for i in range(n):
                p = pos[fi, i]
                c = col[fi, i]
                rows.append(f"{t:.4f},{i},{p[0]:.4f},{p[1]:.4f},{p[2]:.4f},{c[0]:.4f},{c[1]:.4f},{c[2]:.4f}\n")
        zf.writestr("show.csv", "".join(rows))
        zf.writestr("README.txt", "Lumina generic CSV. Coordinates: DSHOW_LOCAL_RH meters. RGB linear 0-1.\n")
    return buf.getvalue()
