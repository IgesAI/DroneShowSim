from __future__ import annotations

import io
import zipfile

from app.models import ShowProject
from app.playback_sample import sample_show


def export_skybrush_csv(project: ShowProject, hz: float = 5.0) -> bytes:
    times, pos, col = sample_show(project, hz)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        n = pos.shape[1]
        for i in range(n):
            lines = ["Time_msec,x_m,y_m,z_m,Red,Green,Blue"]
            for fi, t in enumerate(times):
                p = pos[fi, i]
                c = col[fi, i]
                lines.append(
                    f"{int(round(t * 1000))},{p[0]:.3f},{p[1]:.3f},{p[2]:.3f},"
                    f"{int(round(c[0] * 255))},{int(round(c[1] * 255))},{int(round(c[2] * 255))}"
                )
            zf.writestr(f"drone_{i + 1:04d}.csv", "\n".join(lines))
        zf.writestr(
            "README.txt",
            "Lumina → Skybrush-compatible CSV (independently implemented).\n"
            "One file per drone. Time_msec, x_m, y_m, z_m, RGB 0-255.\n"
            "Coordinates are DSHOW_LOCAL_RH = X right, Y forward, Z up.\n"
            "This adapter does not include Skybrush source code.\n",
        )
    return buf.getvalue()
