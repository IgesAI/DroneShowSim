from __future__ import annotations

import io
import json
import zipfile

from app.models import COMPILER_VERSION, SCHEMA_VERSION, ShowProject
from app.safety.validate import validate_transition


def export_dshow(project: ShowProject) -> bytes:
    reports = []
    formations = {f.id: f for f in project.formations}
    for tr in project.timeline.transitions:
        src, dst = formations.get(tr.fromFormationId), formations.get(tr.toFormationId)
        if src and dst and tr.assignment:
            reports.append(
                validate_transition(src, dst, tr.assignment, tr.duration, project.droneProfile, project.safetyProfile, style=tr.type, mode="full").model_dump()
            )
    manifest = {
        "format": "dshow",
        "version": SCHEMA_VERSION,
        "name": project.name,
        "coordinateSystem": project.coordinateSystem,
        "units": "SI",
        "droneCount": project.droneProfile.count,
        "schemaVersion": SCHEMA_VERSION,
        "compilerVersion": COMPILER_VERSION,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("project.json", project.model_dump_json(indent=2))
        for asset in project.assets:
            ext = "svg" if asset.kind == "svg" else "txt"
            zf.writestr(f"assets/{asset.id}.{ext}", asset.content)
        for formation in project.formations:
            zf.writestr(f"formations/{formation.id}.json", formation.model_dump_json(indent=2))
        zf.writestr("reports/safety.json", json.dumps(reports, indent=2))
    return buf.getvalue()
