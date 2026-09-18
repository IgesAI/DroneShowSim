from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.compile import ensure_formations, solve_timeline
from app.demo import cobra_project
from app.exporters.dshow_zip import export_dshow
from app.exporters.generic_csv import export_generic_csv
from app.exporters.skybrush_csv import export_skybrush_csv
from app.exporters.vviz import export_vviz
from app.formation.sample import generate_formation
from app.models import (
    COMPILER_VERSION,
    SCHEMA_VERSION,
    CompileShowRequest,
    DroneProfile,
    FormationGenerationSettings,
    GenerateFormationRequest,
    SafetyProfile,
    ShowProject,
    SolveTransitionRequest,
    required_separation,
)
from app.safety.validate import validate_transition
from app.transition.assign import assign_formations, swap_worst_crossings
from app.trajectory.minjerk import min_duration

app = FastAPI(title="dshowc", version=COMPILER_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "compiler": COMPILER_VERSION, "schema": SCHEMA_VERSION}


@app.post("/formations/generate")
def formations_generate(req: GenerateFormationRequest):
    formation = generate_formation(
        formation_id=req.assetId,
        name=req.name,
        asset_id=req.assetId,
        content=req.content,
        kind=req.kind,
        count=req.droneCount,
        settings=FormationGenerationSettings(
            mode=req.mode,
            widthM=req.widthMeters,
            heightM=req.heightMeters,
            depthM=req.depthMeters,
            seed=req.seed,
        ),
        color=req.color,
        min_sep_m=required_separation(DroneProfile(count=req.droneCount), SafetyProfile()),
    )
    return {
        "formationId": formation.id,
        "pointCount": len(formation.points),
        "formation": formation.model_dump(),
        "bounds": {
            "width": req.widthMeters,
            "height": req.heightMeters,
            "depth": req.depthMeters,
        },
    }


@app.post("/transitions/solve")
def transitions_solve(req: SolveTransitionRequest):
    assignment = swap_worst_crossings(req.source, req.target, assign_formations(req.source, req.target))
    dists = []
    for a in assignment:
        p0 = req.source.points[a.fromPointId].position
        p1 = req.target.points[a.toPointId].position
        dists.append(((p0[0] - p1[0]) ** 2 + (p0[1] - p1[1]) ** 2 + (p0[2] - p1[2]) ** 2) ** 0.5)
    recommended = max(min_duration(d, req.constraints.maxHorizontalSpeedMps, req.constraints.maxAccelerationMps2) for d in dists)
    duration = recommended if req.duration == "auto" else float(req.duration)
    report = validate_transition(req.source, req.target, assignment, duration, req.constraints, req.safety, style=req.style, mode="full")
    if req.duration == "auto" and report.recommendedDuration:
        duration = report.recommendedDuration
        report = validate_transition(req.source, req.target, assignment, duration, req.constraints, req.safety, style=req.style, mode="full")
    status = "SAFE" if report.passed else "UNSAFE"
    if req.duration == "auto":
        status = "SAFE" if report.passed else "MODIFIED"
    return {
        "transitionId": "trans_001",
        "duration": duration,
        "assignment": [a.model_dump() for a in assignment],
        "minimumSeparation": report.minimumSeparation.value,
        "maximumVelocity": report.maxHorizontalVelocity.value,
        "maximumAcceleration": report.maxAcceleration.value,
        "status": status,
        "safety": report.model_dump(),
    }


@app.post("/shows/compile")
def shows_compile(req: CompileShowRequest):
    project = solve_timeline(req.project, mode=req.mode)
    return {
        "project": project.model_dump(),
        "safety": [],
        "violations": [v.model_dump() for v in project.proximityViolations],
        "notes": [n.model_dump() for n in project.compilerNotes],
    }


@app.post("/shows/demo")
def shows_demo(count: int = 250, seed: int = 1):
    return shows_compile(CompileShowRequest(project=cobra_project(count=count, seed=seed), mode="preview"))


@app.post("/exports/csv")
def exports_csv(req: CompileShowRequest):
    project = solve_timeline(req.project, mode="full")
    return Response(export_generic_csv(project), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=show-generic.csv.zip"})


@app.post("/exports/vviz")
def exports_vviz(req: CompileShowRequest):
    project = solve_timeline(req.project, mode="full")
    return Response(export_vviz(project), media_type="application/json", headers={"Content-Disposition": "attachment; filename=show.vviz"})


@app.post("/exports/skybrush-csv")
def exports_skybrush(req: CompileShowRequest):
    project = solve_timeline(req.project, mode="full")
    return Response(export_skybrush_csv(project), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=show-skybrush-csv.zip"})


@app.post("/exports/dshow")
def exports_dshow(req: CompileShowRequest):
    project = solve_timeline(req.project, mode="full")
    return Response(export_dshow(project), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=show.dshow"})


@app.post("/assets/analyze")
def assets_analyze(req: GenerateFormationRequest):
    return formations_generate(req)


@app.post("/shows/validate")
def shows_validate(req: CompileShowRequest):
    project, _ = ensure_formations(req.project)
    return shows_compile(CompileShowRequest(project=project, mode="full"))
