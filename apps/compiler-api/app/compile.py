from __future__ import annotations

import uuid

from app.formation.launch import generate_launch_grid
from app.formation.sample import ART_FLOOR_Z, SAMPLER_VERSION, generate_formation
from app.models import (
    COMPILER_VERSION,
    SCHEMA_VERSION,
    CompilerNote,
    Cue,
    Formation,
    FormationGenerationSettings,
    ShowProject,
    ShowSlot,
    Transition,
    Violation,
    required_separation,
)
from app.safety.validate import recommended_duration, validate_transition
from app.transition.assign import (
    MORPH_SEPARATION_BOUND,
    assign_formations,
    swap_worst_crossings,
)


LAUNCH_ID = "frm_launch"


def morph_safe_spacing(project: ShowProject) -> float:
    """Point spacing a formation needs so morphing into the next one is legal.

    A synchronised morph under squared-distance assignment dips to
    min(start, end) / sqrt(2) at its tightest. Packing formations at exactly
    the required separation therefore guarantees a violation the moment they
    move, so the margin belongs in the packer rather than in a repair pass.
    """
    return required_separation(project.droneProfile, project.safetyProfile) * MORPH_SEPARATION_BOUND


def ensure_formations(project: ShowProject) -> tuple[ShowProject, set[str]]:
    count = project.droneProfile.count
    rebuilt: set[str] = set()
    for i, formation in enumerate(project.formations):
        if formation.role == "launch":
            continue
        asset = next((a for a in project.assets if a.id == formation.sourceAssetId), None)
        floor = project.venue.groundZ + ART_FLOOR_Z
        ver = formation.generationSettings.samplerVersion if formation.generationSettings else 1
        if formation.points and len(formation.points) == count and ver >= SAMPLER_VERSION:
            if all(p.position[2] >= floor - 1e-6 for p in formation.points):
                continue
        if not asset:
            continue
        settings = formation.generationSettings or FormationGenerationSettings()
        project.formations[i] = generate_formation(
            formation_id=formation.id,
            name=formation.name,
            asset_id=asset.id,
            content=asset.content,
            kind=asset.kind if asset.kind in {"svg", "text", "glb", "obj", "stl"} else "svg",
            count=count,
            settings=settings,
            min_sep_m=morph_safe_spacing(project),
            ground_z=project.venue.groundZ,
            ceiling_z=project.venue.groundZ + project.venue.maxAltitudeM,
        )
        rebuilt.add(formation.id)
    return project, rebuilt


def _launch_reusable(existing: Formation | None, count: int, pitch: float, ground: float) -> bool:
    if existing is None or existing.role != "launch" or len(existing.points) != count:
        return False
    if abs(existing.points[0].position[2] - (ground + 0.12)) > 0.05:
        return False
    if count >= 2:
        dx = abs(existing.points[1].position[0] - existing.points[0].position[0])
        if abs(dx - pitch) > 0.05:
            return False
    return True


def ensure_launch(project: ShowProject, rebuilt: set[str]) -> ShowProject:
    count = project.droneProfile.count
    pitch = project.droneProfile.launchPitchM
    ground = project.venue.groundZ
    existing = next((f for f in project.formations if f.id == LAUNCH_ID), None)
    if _launch_reusable(existing, count, pitch, ground):
        launch = existing
        slots = project.slots if len(project.slots) == count else [ShowSlot(droneId=i, padIndex=i) for i in range(count)]
    else:
        launch, slots = generate_launch_grid(count, pitch, ground, LAUNCH_ID)
        rebuilt.add(LAUNCH_ID)
    project.slots = slots
    others = [f for f in project.formations if f.id != LAUNCH_ID]
    project.formations = [launch, *others]

    launch_hold = 2.0
    land_hold = 2.0
    art: list[Cue] = []
    for cue in project.timeline.cues:
        if cue.id == "cue_launch":
            launch_hold = cue.holdDuration
        elif cue.id == "cue_land":
            land_hold = cue.holdDuration
        elif cue.formationId != LAUNCH_ID:
            cue.phase = "show"
            art.append(cue)

    project.timeline.cues = [
        Cue(id="cue_launch", formationId=LAUNCH_ID, startTime=0, holdDuration=launch_hold, phase="takeoff"),
        *art,
        Cue(id="cue_land", formationId=LAUNCH_ID, startTime=0, holdDuration=land_hold, phase="landing"),
    ]
    return project


def _carry_violations(prev: list[Violation], old_start: float, old_dur: float, new_start: float) -> list[Violation]:
    dt = new_start - old_start
    out: list[Violation] = []
    for v in prev:
        if old_start - 1e-6 <= v.time <= old_start + old_dur + 1e-6:
            out.append(v.model_copy(update={"time": v.time + dt}))
    return out


def solve_timeline(project: ShowProject, mode: str = "preview") -> ShowProject:
    prev_violations = list(project.proximityViolations)
    prev_notes = list(project.compilerNotes)
    project, rebuilt = ensure_formations(project)
    project = ensure_launch(project, rebuilt)
    project.schemaVersion = SCHEMA_VERSION
    project.compilerVersion = COMPILER_VERSION
    notes: list[CompilerNote] = []
    for formation in project.formations:
        if formation.role == "launch":
            continue
        scale = formation.generationSettings.packScale if formation.generationSettings else 1.0
        if scale > 1.05:
            notes.append(
                CompilerNote(
                    kind="art",
                    message=f"{formation.name} grew {scale:.1f}× so the drones stay on the model at safe spacing",
                )
            )
        overflow = sum(1 for p in formation.points if p.importance < 0.61)
        if overflow:
            notes.append(
                CompilerNote(
                    kind="art",
                    message=f"{overflow} extra drones on {formation.name} sit behind after the model hit the size cap",
                )
            )
    violations: list[Violation] = []
    all_ok = True
    cues = project.timeline.cues
    transitions = project.timeline.transitions
    count = project.droneProfile.count
    t = 0.0
    new_cues: list[Cue] = []
    new_trs: list[Transition] = []
    fmap = {f.id: f for f in project.formations}

    for i, cue in enumerate(cues):
        cue.startTime = t
        new_cues.append(cue)
        t += cue.holdDuration
        if i >= len(cues) - 1:
            continue
        nxt = cues[i + 1]
        src = fmap[cue.formationId]
        dst = fmap[nxt.formationId]
        existing = next(
            (tr for tr in transitions if tr.fromFormationId == src.id and tr.toFormationId == dst.id and tr.id not in {x.id for x in new_trs}),
            transitions[i] if i < len(transitions) else None,
        )
        tr = existing or Transition(
            id=f"tr_{uuid.uuid4().hex[:8]}",
            fromFormationId=src.id,
            toFormationId=dst.id,
            startTime=t,
            duration=6.0,
            durationMode="auto",
            type="morph",
            assignment=[],
            trajectorySetId=f"traj_{i:03d}",
        )
        reuse = (
            bool(tr.assignment)
            and len(tr.assignment) == count
            and src.id not in rebuilt
            and dst.id not in rebuilt
            and tr.fromFormationId == src.id
            and tr.toFormationId == dst.id
        )
        phase = nxt.phase if nxt.phase == "landing" else ("takeoff" if cue.phase == "takeoff" else "show")
        old_start, old_dur = tr.startTime, tr.duration
        if not reuse:
            assignment = assign_formations(src, dst)
            assignment = swap_worst_crossings(src, dst, assignment)
            tr.assignment = assignment
        assignment = tr.assignment
        rec = recommended_duration(src, dst, assignment, project.droneProfile, tr.type)
        authored = tr.duration
        if tr.durationMode == "auto":
            tr.duration = round(rec + 0.05, 2)
            if abs(tr.duration - authored) > 0.05:
                notes.append(
                    CompilerNote(
                        kind="safety",
                        transitionId=tr.id,
                        time=t,
                        message=f"Transition {src.name} → {dst.name} set to {tr.duration:.1f}s (was {authored:.1f}s) for velocity/jerk/ascent",
                    )
                )
        skip_validate = reuse and mode == "preview" and abs(tr.duration - old_dur) < 0.05
        tr.fromFormationId = src.id
        tr.toFormationId = dst.id
        tr.startTime = t
        tr.trajectorySetId = f"traj_{i:03d}"
        if skip_validate:
            violations.extend(_carry_violations(prev_violations, old_start, old_dur, t))
            notes.extend(n for n in prev_notes if n.transitionId == tr.id)
        else:
            report = validate_transition(
                src,
                dst,
                assignment,
                tr.duration,
                project.droneProfile,
                project.safetyProfile,
                phase=phase,
                style=tr.type,
                mode=mode,
            )
            for v in report.proximityViolations:
                v.time = tr.startTime + v.time
                violations.append(v)
            if not report.passed and report.recommendedDuration and tr.duration < report.recommendedDuration:
                nxt_dur = round(report.recommendedDuration + 0.1, 2)
                notes.append(
                    CompilerNote(
                        kind="safety",
                        transitionId=tr.id,
                        time=t,
                        message=f"Transition {src.name} → {dst.name} {tr.duration:.1f}s → {nxt_dur:.1f}s to satisfy capsule/accel",
                    )
                )
                tr.duration = nxt_dur
                all_ok = False
            elif not report.passed:
                all_ok = False
        t += tr.duration
        new_trs.append(tr)

    for cue in new_cues:
        for anim in project.timeline.animations:
            if anim.formationId != cue.formationId:
                continue
            if cue.phase in {"takeoff", "landing"}:
                continue
            needed = anim.cueOffset + anim.duration
            if needed > cue.holdDuration:
                extra = needed - cue.holdDuration
                cue.holdDuration += extra
                for later in new_cues:
                    if later.startTime > cue.startTime:
                        later.startTime += extra
                for later in new_trs:
                    if later.startTime >= cue.startTime + (cue.holdDuration - extra):
                        later.startTime += extra
                t += extra
                notes.append(
                    CompilerNote(
                        kind="art",
                        time=cue.startTime,
                        message=f"Hold {cue.formationId} extended by {extra:.1f}s so {anim.name} is not cropped",
                    )
                )

    for anim in project.timeline.animations:
        cue = next((c for c in new_cues if c.formationId == anim.formationId and c.phase == "show"), None)
        if cue:
            anim.startTime = cue.startTime + anim.cueOffset

    project.timeline.cues = new_cues
    project.timeline.transitions = new_trs
    project.timeline.duration = max(t, max((c.startTime + c.holdDuration for c in new_cues), default=t))
    project.compilerNotes = notes
    project.proximityViolations = violations
    project.showState = "VALIDATED" if all_ok and mode == "full" else "COMPILED"
    return project
