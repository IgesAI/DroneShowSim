"""The temporal choreography compiler.

SCENE INTENT → FORMATION GENERATION → EFFECT RESOURCE REQUESTS → ROLE
ALLOCATION → ASSIGNMENT / LOOKAHEAD → DARK STAGING → TRAJECTORY GENERATION →
LIGHTING GENERATION → CONFLICT DETECTION → LOCAL REPAIR → SAFETY VALIDATION →
PER-DRONE PROGRAM COMPILATION.

Lighting generation never bypasses physical validation: validation runs after
lighting and reads only geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Callable

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from app.choreography.allocation import (
    AllocationCandidate,
    AllocationDiagnostics,
    allocate_effect_drones,
    match_to_targets,
)
from app.choreography.assignment import (
    AssignmentDiagnostics,
    SceneAssignmentInputs,
    assign_with_lookahead,
    score_assignment,
)
from app.choreography.audience import AudienceView
from app.choreography.clock import ShowExecutionConfig
from app.choreography.conflict import ConflictGraph, detect_conflicts
from app.choreography.cost import CostWeights
from app.choreography.effects.base import (
    EffectContext,
    EffectFit,
    EnvelopeLimits,
    build_effect,
    fit_effect_to_envelope,
)
from app.choreography.repair import ConflictRepairer, RepairReport, StagedMotion
from app.choreography.sampling import sample_programs, time_grid
from app.choreography.scene import EffectSpec, Scene
from app.choreography.staging import (
    DarkStagingPlanner,
    StagingDiagnostics,
    StagingPlan,
    StagingRequest,
    StagingVolume,
)
from app.choreography.tracks import (
    VISUAL_THRESHOLD,
    CompiledDroneProgram,
    DroneProgram,
    LightingKeyframe,
    LightingTrack,
    RoleSegment,
    RoleTrack,
    TrajectorySegment,
    TrajectoryTrack,
)
from app.choreography.validate import Geofence, ProgramSafetyReport, validate_programs
from app.models import COMPILER_VERSION, Formation, ShowProject, required_separation
from app.safety.geometry import flight_floor
from app.trajectory.minjerk import min_duration
from app.transition.assign import MORPH_SEPARATION_BOUND

ALGORITHM_VERSION = 1
EFFECT_PATH_LEGS = 18

# Dark motion has no artistic constraint, so it may use most of the envelope.
# The remainder is headroom for the repair pass, which only ever slows motion
# down or lengthens its path.
STAGING_SPEED_FACTOR = 0.85

Vec3 = tuple[float, float, float]


# ------------------------------------------------------------------ options


class ChoreographyOptions(BaseModel):
    seed: int = 1
    assignmentLookaheadScenes: int = 1
    weights: CostWeights = Field(default_factory=CostWeights)
    audience: AudienceView = Field(default_factory=AudienceView)
    geofence: Geofence = Field(default_factory=Geofence)
    stagingVolumes: list[StagingVolume] = Field(default_factory=list)
    conflictHz: float = 8.0
    visualThreshold: float = VISUAL_THRESHOLD
    enableDarkStaging: bool = True
    enableRepair: bool = True
    maxRepairs: int = 40


# -------------------------------------------------------------- diagnostics


class SceneSummary(BaseModel):
    sceneId: str
    name: str
    kind: str
    startTime: float
    duration: float
    formationId: str = ""
    droneCount: int = 0
    effectIds: list[str] = Field(default_factory=list)


class EffectDiagnostics(BaseModel):
    effectId: str
    effectName: str
    effectType: str
    anchor: Vec3
    effectBeginsAt: float
    effectEndsAt: float
    allocation: AllocationDiagnostics
    envelopeFit: EffectFit
    staging: StagingDiagnostics
    rejoin: StagingDiagnostics
    visibleFormationPointsReassigned: int = 0
    totalRemovedImportance: float = 0.0
    visibleImpact: str = "estimated low"
    darkTravelDuration: float = 0.0
    # Which drones were taken, and which formation point each gave up. An
    # automatic reassignment nobody can name is not inspectable.
    stagedDroneIds: list[int] = Field(default_factory=list)
    releasedFormationPointIds: list[int] = Field(default_factory=list)


class EffectPlan(BaseModel):
    """Everything an effect settled before any trajectory was written.

    Allocation and the rejoin reassignment both change the backbone, so they
    have to be decided first and applied afterwards.
    """

    model_config = {"arbitrary_types_allowed": True}

    spec: EffectSpec
    effect: object
    ctx: EffectContext
    staging: StagingPlan
    diagnostics: EffectDiagnostics
    stagedIds: list[int] = Field(default_factory=list)
    windowStart: float = 0.0
    effectStart: float = 0.0
    effectEnd: float = 0.0
    rejoinTime: float = 0.0
    returnStart: float = 0.0
    rejoinPositions: dict[int, Vec3] = Field(default_factory=dict)
    holdColors: dict[int, Vec3] = Field(default_factory=dict)
    rejoinColors: dict[int, Vec3] = Field(default_factory=dict)
    holdingFormationId: str = ""
    rejoinFormationId: str = ""
    baseBrightness: float = 1.0


class ChoreographyDiagnostics(BaseModel):
    seed: int
    algorithmVersion: int
    lookaheadHorizon: int
    scenes: list[SceneSummary] = Field(default_factory=list)
    assignment: list[AssignmentDiagnostics] = Field(default_factory=list)
    effects: list[EffectDiagnostics] = Field(default_factory=list)
    conflictsBefore: ConflictGraph = Field(default_factory=ConflictGraph)
    conflictsAfter: ConflictGraph = Field(default_factory=ConflictGraph)
    repairs: RepairReport = Field(default_factory=RepairReport)
    notes: list[str] = Field(default_factory=list)


class Choreography(BaseModel):
    version: str = "1.0.0"
    compilerVersion: str = COMPILER_VERSION
    algorithmVersion: int = ALGORITHM_VERSION
    seed: int = 1
    duration: float = 0.0
    scenes: list[Scene] = Field(default_factory=list)
    programs: list[DroneProgram] = Field(default_factory=list)
    compiled: list[CompiledDroneProgram] = Field(default_factory=list)
    audience: AudienceView = Field(default_factory=AudienceView)
    stagingVolumes: list[StagingVolume] = Field(default_factory=list)
    execution: ShowExecutionConfig = Field(default_factory=ShowExecutionConfig)
    safety: ProgramSafetyReport | None = None
    diagnostics: ChoreographyDiagnostics | None = None


# ------------------------------------------------------------------ helpers


def derive_scenes(project: ShowProject) -> list[Scene]:
    """Legacy projects author cues, not scenes. Give them scenes anyway."""
    scenes: list[Scene] = []
    for cue in sorted(project.timeline.cues, key=lambda c: c.startTime):
        kind = (
            "TAKEOFF"
            if cue.phase == "takeoff"
            else "LANDING"
            if cue.phase == "landing"
            else "FORMATION"
        )
        scenes.append(
            Scene(
                id=f"scene_{cue.id}",
                name=cue.formationId,
                kind=kind,  # type: ignore[arg-type]
                startTime=cue.startTime,
                duration=cue.holdDuration,
                formationIds=[cue.formationId],
            )
        )
    return scenes


def resolve_scenes(project: ShowProject) -> list[Scene]:
    """Merge authored intent onto the timing the timeline solver produced."""
    backbone = derive_scenes(project)
    authored = {
        s.formationIds[0]: s
        for s in project.scenes
        if s.kind != "EFFECT" and s.formationIds
    }
    for scene in backbone:
        source = authored.get(scene.formationIds[0])
        if source is None:
            continue
        scene.id = source.id or scene.id
        scene.name = source.name or scene.name
        scene.lighting = source.lighting
        scene.transition = source.transition
        scene.metadata = source.metadata
        if source.kind != "FORMATION":
            scene.kind = source.kind

    by_formation = {s.formationIds[0]: s for s in backbone}
    overlays: list[Scene] = []
    for scene in project.scenes:
        if scene.kind != "EFFECT":
            continue
        host = by_formation.get(scene.hostFormationId or "")
        if host is None:
            continue
        span = max(
            (e.startOffset + e.duration for e in scene.effects),
            default=scene.duration,
        )
        overlays.append(
            scene.model_copy(
                update={
                    "startTime": host.startTime + scene.hostOffsetS,
                    "duration": max(span, scene.duration),
                }
            )
        )
    return [*backbone, *overlays]


def resolve_anchor(spec: EffectSpec, formations: dict[str, Formation]) -> Vec3:
    if spec.anchorMode == "explicit" or not spec.anchorFormationId:
        if spec.anchorPosition is not None:
            return _offset(spec.anchorPosition, spec.anchorOffset)
        param = (spec.parameters or {}).get("anchorPosition")
        if param:
            return _offset(tuple(param), spec.anchorOffset)  # type: ignore[arg-type]
        return _offset((0.0, 0.0, 30.0), spec.anchorOffset)

    formation = formations.get(spec.anchorFormationId)
    if formation is None or not formation.points:
        return _offset((0.0, 0.0, 30.0), spec.anchorOffset)

    pool = [p for p in formation.points if p.importance >= spec.anchorImportanceMin] or formation.points
    if spec.anchorMode == "formation-centroid":
        cx = sum(p.position[0] for p in pool) / len(pool)
        cy = sum(p.position[1] for p in pool) / len(pool)
        cz = sum(p.position[2] for p in pool) / len(pool)
        return _offset((cx, cy, cz), spec.anchorOffset)

    axis = spec.anchorAxis
    best = max(
        pool,
        key=lambda p: (
            round(p.position[0] * axis[0] + p.position[1] * axis[1] + p.position[2] * axis[2], 6),
            p.id,
        ),
    )
    return _offset(best.position, spec.anchorOffset)


def _offset(p: Vec3, d: Vec3) -> Vec3:
    return (p[0] + d[0], p[1] + d[1], p[2] + d[2])


def _synchronised_separation(starts: list[Vec3], ends: list[Vec3], samples: int = 24) -> float:
    """Closest approach of a group flying a shared min-jerk time base."""
    if len(starts) < 2:
        return math.inf
    a = np.array(starts, dtype=np.float64)
    b = np.array(ends, dtype=np.float64)
    worst = math.inf
    for k in range(samples + 1):
        u = k / samples
        s = u * u * u * (10.0 + u * (-15.0 + 6.0 * u))
        frame = a + s * (b - a)
        d, _ = cKDTree(frame).query(frame, k=2)
        worst = min(worst, float(d[:, 1].min()))
    return worst


def _chain_mappings(
    project: ShowProject,
    chain: list[tuple[Scene, Formation]],
    arrays: list[np.ndarray],
    inputs: list[SceneAssignmentInputs],
    options: ChoreographyOptions,
) -> tuple[list[dict[int, int]], list[AssignmentDiagnostics]]:
    """Phase 1 reuses the timeline's pairwise solution so the compiled
    programs agree with the durations the timeline solver already validated.
    Lookahead is opt-in and re-solves the chain itself.
    """
    if options.assignmentLookaheadScenes <= 1:
        reuse: list[dict[int, int]] = []
        for k in range(len(chain) - 1):
            src_id, dst_id = chain[k][1].id, chain[k + 1][1].id
            transition = next(
                (
                    t
                    for t in project.timeline.transitions
                    if t.fromFormationId == src_id and t.toFormationId == dst_id and t.assignment
                ),
                None,
            )
            if transition is None:
                reuse = []
                break
            reuse.append({a.fromPointId: a.toPointId for a in transition.assignment})
        if reuse and len(reuse) == len(chain) - 1:
            diagnostics = []
            for k, mapping in enumerate(reuse):
                d = score_assignment(
                    arrays[k],
                    arrays[k + 1],
                    mapping,
                    options.weights,
                    src=inputs[k],
                    dst=inputs[k + 1],
                    view=options.audience,
                )
                d.horizon = 1
                d.baselineTotalCost = d.totalCost
                diagnostics.append(d)
            return reuse, diagnostics

    return assign_with_lookahead(
        arrays,
        options.weights,
        horizon=options.assignmentLookaheadScenes,
        inputs=inputs,
        view=options.audience,
    )


def _feature_role(importance: float) -> str:
    return "core" if importance >= 0.61 else "detail"


def _content_hash(program: DroneProgram, seed: int, revision: str) -> str:
    payload = json.dumps(
        {
            "drone": program.droneId,
            "trajectory": program.trajectoryTrack.model_dump(),
            "lighting": program.lightingTrack.model_dump(),
            "roles": program.roleTrack.model_dump(),
            "seed": seed,
            "revision": revision,
            "algorithm": ALGORITHM_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ----------------------------------------------------------------- compiler


def compile_choreography(
    project: ShowProject,
    options: ChoreographyOptions | None = None,
) -> Choreography:
    options = options or ChoreographyOptions()
    profile = project.droneProfile
    safety = project.safetyProfile
    ground = project.venue.groundZ
    req_sep = required_separation(profile, safety)
    n = profile.count

    formations = {f.id: f for f in project.formations}
    scenes = sorted(resolve_scenes(project), key=lambda s: s.startTime)
    backbone = [s for s in scenes if s.kind != "EFFECT" and s.formationIds]
    overlays = [s for s in scenes if s.kind == "EFFECT"]
    notes: list[str] = []

    chain: list[tuple[Scene, Formation]] = []
    for scene in backbone:
        formation = formations.get(scene.formationIds[0])
        if formation and formation.points:
            chain.append((scene, formation))
        else:
            notes.append(f"scene {scene.id} skipped: formation has no points")

    if not chain:
        return Choreography(seed=options.seed, scenes=scenes)

    # --- ASSIGNMENT / LOOKAHEAD ------------------------------------------
    arrays = [
        np.array([p.position for p in f.points[:n]], dtype=np.float64) for _, f in chain
    ]
    inputs = [
        SceneAssignmentInputs(
            importance=[p.importance for p in f.points[:n]],
            roleIds=[_feature_role(p.importance) for p in f.points[:n]],
            brightness=[s.lighting.baseBrightness] * min(n, len(f.points)),
        )
        for s, f in chain
    ]
    mappings, assign_diags = _chain_mappings(project, chain, arrays, inputs, options)
    if any(not d.exactSolve for d in assign_diags):
        notes.append(
            f"fleet of {n} exceeds the exact assignment ceiling; those legs were solved "
            "greedily and carry no separation bound, so the conflict pass is the only check"
        )

    width = min(n, min(len(a) for a in arrays))
    indices: list[list[int]] = [list(range(width))]
    for leg, mapping in enumerate(mappings):
        prev = indices[-1]
        indices.append([mapping.get(prev[i], prev[i] % len(arrays[leg + 1])) for i in range(width)])

    # --- EFFECT RESOURCE REQUESTS / ROLE ALLOCATION / DARK STAGING --------
    # Planned before any trajectory exists. Borrowing a drone for an effect
    # also changes which point of the *next* formation it returns to, and
    # that has to be settled before the backbone is written or the drone ends
    # up flying home to one point and holding at another.
    planner = DarkStagingPlanner(profile, safety)
    plans: list[EffectPlan] = []
    claimed: set[int] = set()
    for scene in overlays:
        for spec in scene.effects:
            plan = _plan_effect(
                spec=spec,
                scene=scene,
                chain=chain,
                indices=indices,
                width=width,
                formations=formations,
                planner=planner,
                options=options,
                req_sep=req_sep,
                claimed=claimed,
                notes=notes,
            )
            if plan is None:
                continue
            plans.append(plan)
            claimed |= set(plan.stagedIds)

    # --- TRAJECTORY + LIGHTING + ROLE GENERATION (backbone) ---------------
    programs: dict[int, DroneProgram] = {}
    for i in range(width):
        traj = TrajectoryTrack()
        light = LightingTrack()
        roles = RoleTrack()
        for k, (scene, formation) in enumerate(chain):
            point = formation.points[indices[k][i]]
            p: Vec3 = tuple(point.position)  # type: ignore[assignment]
            hold_end = scene.endTime
            traj.segments.append(
                TrajectorySegment(
                    startTime=scene.startTime,
                    duration=max(scene.duration, 1e-3),
                    start=p,
                    end=p,
                    style="hold",
                    floorZ=flight_floor(p[2], p[2], ground),
                    sourceId=f"hold:{scene.id}",
                )
            )
            base_b = 0.0 if scene.lighting.mode == "blackout" else scene.lighting.baseBrightness
            rgb = scene.lighting.rgbLinear or tuple(point.color)
            light.keyframes.append(
                LightingKeyframe(time=scene.startTime, rgbLinear=rgb, brightness=base_b)  # type: ignore[arg-type]
            )
            light.keyframes.append(
                LightingKeyframe(time=hold_end, rgbLinear=rgb, brightness=base_b)  # type: ignore[arg-type]
            )
            role_type = (
                "TAKEOFF"
                if scene.kind == "TAKEOFF"
                else "RTH"
                if scene.kind in {"RTH", "LANDING"}
                else "FORMATION"
            )
            role_end = chain[k + 1][0].startTime if k + 1 < len(chain) else hold_end
            roles.segments.append(
                RoleSegment(
                    startTime=scene.startTime,
                    endTime=max(role_end, hold_end),
                    roleType=role_type,  # type: ignore[arg-type]
                    roleId=formation.id,
                    metadata={"feature": _feature_role(point.importance), "importance": point.importance},
                )
            )
            if k + 1 < len(chain):
                nxt_scene, nxt_formation = chain[k + 1]
                q: Vec3 = tuple(nxt_formation.points[indices[k + 1][i]].position)  # type: ignore[assignment]
                gap = max(nxt_scene.startTime - hold_end, 1e-3)
                traj.segments.append(
                    TrajectorySegment(
                        startTime=hold_end,
                        duration=gap,
                        start=p,
                        end=q,
                        style="minjerk",
                        floorZ=flight_floor(p[2], q[2], ground),
                        sourceId=f"transit:{scene.id}->{nxt_scene.id}",
                    )
                )
        programs[i] = DroneProgram(
            droneId=i, trajectoryTrack=traj, lightingTrack=light, roleTrack=roles
        ).normalize()

    # --- EFFECT SPLICING: dark exit, effect motion, dark rejoin -----------
    effect_diags: list[EffectDiagnostics] = []
    motions: dict[int, StagedMotion] = {}
    rebuilders: dict[int, Callable[[StagedMotion], None]] = {}
    for plan in plans:
        new_motions, new_rebuilders = _apply_effect(plan, programs, planner, ground)
        effect_diags.append(plan.diagnostics)
        motions.update(new_motions)
        rebuilders.update(new_rebuilders)

    program_list = [programs[i] for i in sorted(programs)]
    duration = max((p.trajectoryTrack.endTime for p in program_list), default=0.0)

    # --- CONFLICT DETECTION ----------------------------------------------
    before = detect_conflicts(
        program_list, profile, safety, end=duration, hz=options.conflictHz
    )

    # --- LOCAL REPAIR -----------------------------------------------------
    repairs = RepairReport()
    after = before
    if options.enableRepair and before.errors() and motions:

        def rebuild(motion: StagedMotion) -> None:
            fn = rebuilders.get(motion.droneId)
            if fn:
                fn(motion)

        repairer = ConflictRepairer(programs, motions, rebuild, profile, safety)
        repairs = repairer.repair(before, max_conflicts=options.maxRepairs)
        if repairs.applied_records:
            program_list = [programs[i] for i in sorted(programs)]
            duration = max((p.trajectoryTrack.endTime for p in program_list), default=0.0)
            after = detect_conflicts(
                program_list, profile, safety, end=duration, hz=options.conflictHz
            )

    # --- SAFETY VALIDATION (all drones, lit or dark) ----------------------
    geofence = options.geofence.model_copy(update={"groundZ": ground})
    sampled = sample_programs(program_list, time_grid(0.0, max(duration, 0.1), options.conflictHz))
    report = validate_programs(
        program_list,
        profile,
        safety,
        geofence=geofence,
        hz=options.conflictHz,
        end=duration,
        sampled=sampled,
        visual_threshold=options.visualThreshold,
    )

    # --- PER-DRONE PROGRAM COMPILATION ------------------------------------
    revision = f"{project.id}:{len(project.formations)}:{len(scenes)}"
    compiled = [
        CompiledDroneProgram(
            logicalDroneId=p.droneId,
            trajectory=p.trajectoryTrack,
            lighting=p.lightingTrack,
            roles=p.roleTrack,
            compilerVersion=COMPILER_VERSION,
            sourceProjectRevision=revision,
            seed=options.seed,
            algorithmVersion=ALGORITHM_VERSION,
            contentHash=_content_hash(p, options.seed, revision),
            duration=duration,
        )
        for p in program_list
    ]

    diagnostics = ChoreographyDiagnostics(
        seed=options.seed,
        algorithmVersion=ALGORITHM_VERSION,
        lookaheadHorizon=options.assignmentLookaheadScenes,
        scenes=[
            SceneSummary(
                sceneId=s.id,
                name=s.name,
                kind=s.kind,
                startTime=s.startTime,
                duration=s.duration,
                formationId=s.formationIds[0] if s.formationIds else "",
                droneCount=width,
                effectIds=[e.id for e in s.effects],
            )
            for s in scenes
        ],
        assignment=assign_diags,
        effects=effect_diags,
        conflictsBefore=before,
        conflictsAfter=after,
        repairs=repairs,
        notes=notes,
    )

    return Choreography(
        seed=options.seed,
        duration=duration,
        scenes=scenes,
        programs=program_list,
        compiled=compiled,
        audience=options.audience,
        stagingVolumes=options.stagingVolumes,
        execution=ShowExecutionConfig(state="LOADED"),
        safety=report,
        diagnostics=diagnostics,
    )


# ------------------------------------------------------------ effect compile


def _staging_corridor(
    held: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    audience: AudienceView,
    clearance: float,
    requested: float,
    samples: int = 14,
) -> tuple[Vec3 | None, float]:
    """How far back the group must withdraw to cross in clear air.

    Measured rather than assumed. Pushing back far enough to clear the
    deepest point of the destination is always safe and usually wasteful —
    on the demo it cost 20 m each way, more dark travel than the window
    holds — because most of the destination is nowhere near the formation.
    So take the shallowest withdrawal that actually keeps the routes clear.

    Horizontal only: dropping the corridor below the formation would eat into
    the altitude budget and put the group in the descent-rate limit for no
    reason.
    """
    if len(held) == 0 or len(starts) == 0:
        return None, 0.0
    away = np.array(audience.position, dtype=np.float64) - held.mean(axis=0)
    away[2] = 0.0
    norm = float(np.linalg.norm(away))
    if norm < 1e-6:
        return None, 0.0
    n = away / norm
    tree = cKDTree(held)
    span = float((ends @ n).max() - (held @ n).min()) + clearance
    u = np.linspace(0.0, 1.0, samples)[:, None, None]

    def clear_at(depth: float) -> float:
        back = -depth * n
        legs = (
            (starts, starts + back),
            (starts + back, ends + back),
            (ends + back, ends),
        )
        worst = math.inf
        for a, b in legs:
            pts = (a + u * (b - a)).reshape(-1, 3)
            worst = min(worst, float(tree.query(pts, k=1)[0].min()))
        return worst

    ladder = [requested] if requested > 1e-6 else []
    ladder += list(np.arange(clearance, span + 2.0, 2.0)) + [span]
    for depth in ladder:
        if clear_at(float(depth)) >= clearance:
            return (float(n[0]), float(n[1]), float(n[2])), float(depth)
    return (float(n[0]), float(n[1]), float(n[2])), float(span)


def _plan_effect(
    *,
    spec: EffectSpec,
    scene: Scene,
    chain: list[tuple[Scene, Formation]],
    indices: list[list[int]],
    width: int,
    formations: dict[str, Formation],
    planner: DarkStagingPlanner,
    options: ChoreographyOptions,
    req_sep: float,
    claimed: set[int],
    notes: list[str],
) -> "EffectPlan | None":
    effect_start = scene.startTime + spec.startOffset
    effect_end = effect_start + (spec.duration or scene.duration)

    holding_index = None
    for k, (s, _f) in enumerate(chain):
        if s.startTime - 1e-6 <= effect_start < s.endTime + 1e-6:
            holding_index = k
    if holding_index is None:
        notes.append(f"effect {spec.id} has no holding scene at {effect_start:.2f}s")
        return None

    holding_scene, holding_formation = chain[holding_index]
    rejoin_index = holding_index + 1 if holding_index + 1 < len(chain) else holding_index
    rejoin_scene, rejoin_formation = chain[rejoin_index]
    rejoin_time = rejoin_scene.startTime if rejoin_index != holding_index else holding_scene.endTime
    if rejoin_time <= effect_end:
        rejoin_time = effect_end + 2.0

    anchor = resolve_anchor(spec, formations)

    # --- EFFECT RESOURCE REQUEST ------------------------------------------
    # Fit the effect before allocating: the envelope clamp changes how many
    # drones the geometry can actually hold, and allocating first would hand
    # the staging planner a crowd that cannot fit where it is being sent.
    effect = build_effect(spec)
    authored = max(effect_end - effect_start, 1e-3)
    latest_end = max(rejoin_time - spec.stagingMarginS, effect_start + authored)
    # The plume is laid out with the morph margin, not the bare minimum: the
    # staged drones converge on it from the formation, and a converging flow
    # dips to min(start, end) / sqrt(2) on the way in.
    probe = EffectContext(
        anchor=anchor,
        droneCount=max(spec.resources.maximum, spec.resources.preferred),
        minSeparationM=req_sep * MORPH_SEPARATION_BOUND,
        seed=options.seed,
        startTime=effect_start,
        duration=authored,
    )
    fit, ctx = fit_effect_to_envelope(
        effect,
        probe,
        EnvelopeLimits(
            speed=planner.profile.maxHorizontalSpeedMps * 0.85,
            acceleration=planner.profile.maxAccelerationMps2 * 0.85,
            jerk=planner.profile.maxJerkMps3 * 0.85,
        ),
        max_time_stretch=max(1.0, (latest_end - effect_start) / authored),
    )
    for note in fit.notes:
        notes.append(f"effect {spec.id} {note}")
    if fit.exceedsEnvelope:
        notes.append(f"effect {spec.id} still exceeds {fit.speedLimit:.1f} m/s after fitting")
    effect_end = effect_start + ctx.duration
    if rejoin_time <= effect_end + spec.stagingMarginS:
        rejoin_time = effect_end + spec.stagingMarginS + 1.5

    # --- ROLE ALLOCATION --------------------------------------------------
    candidates = [
        AllocationCandidate(
            droneId=i,
            position=tuple(holding_formation.points[indices[holding_index][i]].position),  # type: ignore[arg-type]
            importance=holding_formation.points[indices[holding_index][i]].importance,
            roleType="FORMATION",
            roleId=holding_formation.id,
            formationPointId=indices[holding_index][i],
            brightness=holding_scene.lighting.baseBrightness,
        )
        for i in range(width)
        if i not in claimed
    ]
    request = spec.resources.capped(fit.capacity, fleet=width)
    if request.preferred < spec.resources.preferred:
        notes.append(
            f"effect {spec.id} scaled from {spec.resources.preferred} drones to "
            f"{request.preferred} for a fleet of {width}"
        )
    allocation = allocate_effect_drones(spec.id, request, candidates, anchor)
    if not allocation.droneIds:
        notes.append(f"effect {spec.id} allocated no drones")
        return None

    ctx = ctx.model_copy(update={"droneCount": len(allocation.droneIds)})
    entry = [t.position for t in effect.entry_targets(ctx)]
    exits = [t.position for t in effect.exit_targets(ctx)]

    # --- DARK STAGING PLANNING -------------------------------------------
    # The drones left behind are holding still, so there is no shared time
    # base with them and no separation bound across the crossing. Send the
    # group out the back of the formation instead: the withdrawal is one
    # translation shared by the whole group, which cannot change any
    # separation, and the crossing then happens in empty air.
    borrowed = {c.droneId for c in allocation.candidates}
    held = np.array(
        [
            holding_formation.points[indices[holding_index][i]].position
            for i in range(width)
            if i not in borrowed
        ],
        dtype=np.float64,
    )
    normal, depth = _staging_corridor(
        held,
        np.array([c.position for c in allocation.candidates], dtype=np.float64),
        np.array(entry, dtype=np.float64),
        options.audience,
        req_sep,
        spec.corridorDepthM,
    )
    shift = tuple(-depth * c for c in normal) if normal else None

    # `maxStagingLeadS` is a preference, not a limit. Physics decides how much
    # dark time the group actually needs; going dark earlier than that is
    # pointless, going dark later is impossible.
    needed = planner.required_lead(
        allocation.candidates, entry, spec.stagingMarginS, STAGING_SPEED_FACTOR, depth
    )
    lead = max(spec.maxStagingLeadS, needed)
    earliest = max(holding_scene.startTime + 0.25, effect_start - lead)
    if needed > spec.maxStagingLeadS + 1e-6:
        notes.append(
            f"effect {spec.id} needs {needed:.1f}s of dark travel, "
            f"more than the {spec.maxStagingLeadS:.1f}s preferred lead"
        )
    volumes = [v for v in options.stagingVolumes if v.priority >= 0]
    plan = planner.plan(
        StagingRequest(
            label=spec.id,
            requiredArrivalTime=effect_start,
            earliestStart=earliest,
            candidates=allocation.candidates,
            targets=entry,
            volumes=volumes,
            marginS=spec.stagingMarginS,
            speedFactor=STAGING_SPEED_FACTOR,
            roleId=spec.id,
            corridorShift=shift,  # type: ignore[arg-type]
        )
    )
    if plan.diagnostics.rejected and not options.enableDarkStaging:
        notes.append(f"effect {spec.id} staging rejected: {plan.diagnostics.notes}")
        return None

    hold_colors = {
        i: tuple(holding_formation.points[indices[holding_index][i]].color) for i in range(width)
    }

    # --- REJOIN: one fleet, one time base, one assignment ------------------
    # The backbone picked each drone's next formation point before the effect
    # existed, and those pairings are now wrong: the borrowed drones are in a
    # plume, not in the dragon.
    #
    # Reassigning only among the borrowed drones is not enough. The other 436
    # fly the same stretch of sky to the same formation at the same time, and
    # an assignment that is optimal within a subset says nothing about the gap
    # between a drone in that subset and one outside it — measured here, a
    # rejoining drone passed a transiting one at 2.70 m against a 3.70 m
    # requirement. Re-solving the whole formation from where every drone
    # actually is, and flying it on the transit's own clock, puts all 500 back
    # under the same min(start, end) / sqrt(2) guarantee.
    staged_ids = [a.droneId for a in plan.assignments]
    staged_set = set(staged_ids)
    exit_by_drone = {
        a.droneId: (exits[a.targetIndex] if a.targetIndex < len(exits) else a.toPosition)
        for a in plan.assignments
    }

    transit_start = holding_scene.endTime
    shared_clock = effect_end <= transit_start + 1e-6 and transit_start < rejoin_time
    if not shared_clock:
        notes.append(
            f"effect {spec.id} ends at {effect_end:.1f}s, after the transit to "
            f"{rejoin_formation.id} begins at {transit_start:.1f}s; the flight home is "
            "planned on its own clock and cannot share the fleet's separation bound"
        )

    origin_at_transit = {
        i: (
            exit_by_drone[i]
            if i in staged_set
            else tuple(holding_formation.points[indices[holding_index][i]].position)
        )
        for i in range(width)
    }
    slots = [indices[rejoin_index][i] for i in range(width)]
    fleet_match = match_to_targets(
        [AllocationCandidate(droneId=i, position=origin_at_transit[i]) for i in range(width)],  # type: ignore[arg-type]
        [tuple(rejoin_formation.points[s].position) for s in slots],  # type: ignore[misc]
    )
    # Taking another drone's formation point means taking its place in every
    # formation after it too, or it would land on a pad it never flew to.
    tails = {i: [indices[m][i] for m in range(rejoin_index, len(indices))] for i in range(width)}
    owner = {slot: drone for drone, slot in enumerate(slots)}
    for cand, slot_index in fleet_match:
        source = owner[slots[slot_index]]
        for offset, m in enumerate(range(rejoin_index, len(indices))):
            indices[m][cand.droneId] = tails[source][offset]

    rejoin_positions = {
        i: tuple(rejoin_formation.points[indices[rejoin_index][i]].position)
        for i in range(width)
    }
    rejoin_colors = {
        i: tuple(rejoin_formation.points[indices[rejoin_index][i]].color) for i in range(width)
    }

    if shared_clock:
        return_start = transit_start
    else:
        rejoin_lead = max(
            (
                planner.travel_time(
                    math.dist(exit_by_drone[i], rejoin_positions[i]),
                    rejoin_positions[i][2] - exit_by_drone[i][2],
                    STAGING_SPEED_FACTOR,
                )
                + spec.stagingMarginS
                for i in staged_ids
            ),
            default=0.0,
        )
        return_start = max(effect_end, min(rejoin_time - rejoin_lead, rejoin_time - 1e-3))

    rejoin_windows = [
        planner.window(
            drone_id,
            exit_by_drone[drone_id],
            rejoin_positions[drone_id],  # type: ignore[arg-type]
            rejoin_time,
            return_start,
            0.0,
            STAGING_SPEED_FACTOR,
        )
        for drone_id in staged_ids
    ]

    # Measured across the whole fleet when it shares the transit clock: the
    # rejoining drones are not alone in that airspace, and a figure that only
    # looked at the borrowed 64 would report a gap the show never has.
    measured_ids = list(range(width)) if shared_clock else staged_ids
    rejoin_sep = _synchronised_separation(
        [origin_at_transit[i] for i in measured_ids],  # type: ignore[misc]
        [rejoin_positions[i] for i in measured_ids],  # type: ignore[misc]
    )
    rejoin_diag = StagingDiagnostics(
        label=f"{spec.id}:rejoin",
        droneCount=len(rejoin_windows),
        stagingBeginsAt=round(return_start, 4),
        eventBeginsAt=round(rejoin_time, 4),
        darkTravelDuration=round(rejoin_time - return_start, 4),
        maximumStagingVelocity=round(max((w.maximumVelocity for w in rejoin_windows), default=0.0), 4),
        maximumStagingAcceleration=round(
            max((w.maximumAcceleration for w in rejoin_windows), default=0.0), 4
        ),
        minimumPredictedSeparation=round(rejoin_sep, 4) if math.isfinite(rejoin_sep) else -1.0,
        requiredSeparation=round(req_sep, 4),
        infeasibleDrones=sorted(w.droneId for w in rejoin_windows if not w.feasible),
        rejected=any(not w.feasible for w in rejoin_windows) or rejoin_sep < req_sep,
        notes=[w.reason for w in rejoin_windows if w.reason][:6],
    )

    removed = allocation.diagnostics.removedImportance
    impact = (
        "estimated low"
        if removed <= len(allocation.droneIds) * 0.55
        else "estimated moderate"
        if removed <= len(allocation.droneIds) * 0.8
        else "estimated high"
    )

    diag = EffectDiagnostics(
        effectId=spec.id,
        effectName=spec.name or spec.id,
        effectType=spec.type,
        anchor=anchor,
        effectBeginsAt=round(effect_start, 4),
        effectEndsAt=round(effect_end, 4),
        allocation=allocation.diagnostics,
        envelopeFit=fit,
        staging=plan.diagnostics,
        rejoin=rejoin_diag,
        visibleFormationPointsReassigned=len(allocation.droneIds),
        totalRemovedImportance=removed,
        visibleImpact=impact,
        darkTravelDuration=plan.diagnostics.darkTravelDuration,
        stagedDroneIds=sorted(allocation.droneIds),
        releasedFormationPointIds=sorted(
            c.formationPointId for c in allocation.candidates if c.formationPointId is not None
        ),
    )
    return EffectPlan(
        spec=spec,
        effect=effect,
        ctx=ctx,
        staging=plan,
        diagnostics=diag,
        stagedIds=staged_ids,
        windowStart=earliest,
        effectStart=effect_start,
        effectEnd=effect_end,
        rejoinTime=rejoin_time,
        returnStart=return_start,
        rejoinPositions={i: rejoin_positions[i] for i in staged_ids},  # type: ignore[misc]
        holdColors={i: hold_colors[i] for i in staged_ids},  # type: ignore[misc]
        rejoinColors={i: rejoin_colors[i] for i in staged_ids},  # type: ignore[misc]
        holdingFormationId=holding_formation.id,
        rejoinFormationId=rejoin_formation.id,
        baseBrightness=holding_scene.lighting.baseBrightness,
    )


def _apply_effect(
    plan: "EffectPlan",
    programs: dict[int, DroneProgram],
    planner: DarkStagingPlanner,
    ground: float,
) -> tuple[dict[int, StagedMotion], dict[int, Callable[[StagedMotion], None]]]:
    """Splice each borrowed drone's dark exit, effect and dark rejoin."""
    motions: dict[int, StagedMotion] = {}
    rebuilders: dict[int, Callable[[StagedMotion], None]] = {}
    for assignment in plan.staging.assignments:
        drone_id = assignment.droneId
        motion = StagedMotion(
            droneId=drone_id,
            groupId=plan.spec.id,
            targetIndex=assignment.targetIndex,
            windowStart=plan.windowStart,
            startTime=assignment.startTime,
            arrivalTime=plan.effectStart,
            holdUntil=plan.rejoinTime,
            fromPosition=assignment.fromPosition,
            toPosition=assignment.toPosition,
            waypoints=list(assignment.waypoints),
            style=assignment.style,
            floorZ=flight_floor(assignment.fromPosition[2], assignment.toPosition[2], ground),
            returnStart=plan.returnStart,
            returnTo=plan.rejoinPositions[drone_id],
        )
        rebuild = _make_rebuilder(
            spec=plan.spec,
            effect=plan.effect,
            ctx=plan.ctx,
            program=programs[drone_id],
            planner=planner,
            effect_start=plan.effectStart,
            effect_end=plan.effectEnd,
            rejoin_time=plan.rejoinTime,
            returnStart=plan.returnStart,
            rejoin_position=plan.rejoinPositions[drone_id],
            hold_color=plan.holdColors[drone_id],
            rejoin_color=plan.rejoinColors[drone_id],
            holding_formation_id=plan.holdingFormationId,
            rejoin_formation_id=plan.rejoinFormationId,
            base_brightness=plan.baseBrightness,
            ground=ground,
        )
        rebuild(motion)
        motions[drone_id] = motion
        rebuilders[drone_id] = rebuild
    return motions, rebuilders


def _make_rebuilder(
    *,
    spec: EffectSpec,
    effect,
    ctx: EffectContext,
    program: DroneProgram,
    planner: DarkStagingPlanner,
    effect_start: float,
    effect_end: float,
    rejoin_time: float,
    returnStart: float,
    rejoin_position: Vec3,
    hold_color: Vec3,
    rejoin_color: Vec3,
    holding_formation_id: str,
    rejoin_formation_id: str,
    base_brightness: float,
    ground: float,
) -> Callable[[StagedMotion], None]:
    """Regenerates one drone's staged window. Idempotent, so repairs can retry."""

    path_cache: dict[int, list[Vec3]] = {}

    def effect_path(index: int) -> list[Vec3]:
        cached = path_cache.get(index)
        if cached is not None:
            return cached
        pts: list[Vec3] = []
        for k in range(EFFECT_PATH_LEGS + 1):
            sample = effect.sample(k / EFFECT_PATH_LEGS, ctx)
            if index < len(sample.targets):
                pts.append(sample.targets[index].position)
        path_cache[index] = pts
        return pts

    def rebuild(motion: StagedMotion) -> None:
        path = effect_path(motion.targetIndex)
        entry_point: Vec3 = path[0] if path else motion.toPosition
        window_start = min(motion.windowStart, motion.startTime)

        segments: list[TrajectorySegment] = []

        # 1. stay put until it is actually time to leave
        if motion.startTime > window_start + 1e-6:
            segments.append(
                TrajectorySegment(
                    startTime=window_start,
                    duration=motion.startTime - window_start,
                    start=motion.fromPosition,
                    end=motion.fromPosition,
                    style="hold",
                    floorZ=flight_floor(motion.fromPosition[2], motion.fromPosition[2], ground),
                    sourceId=f"hold:{holding_formation_id}",
                )
            )

        # 2. dark travel to the staging point (optionally via waypoints)
        approach = 0.0
        park = motion.toPosition
        if math.dist(park, entry_point) > 1e-6:
            approach = max(
                0.5,
                min_duration(
                    math.dist(park, entry_point),
                    planner.profile.maxHorizontalSpeedMps * 0.5,
                    planner.profile.maxAccelerationMps2 * 0.5,
                ),
            )
            approach = min(approach, max(motion.arrivalTime - motion.startTime - 0.2, 0.0))

        legs = [motion.fromPosition, *motion.waypoints, park]
        travel_span = max(motion.arrivalTime - approach - motion.startTime, 1e-3)
        t = motion.startTime
        if motion.style == "spline" and len(legs) > 2:
            zs = [p[2] for p in legs]
            segments.append(
                TrajectorySegment(
                    startTime=t,
                    duration=travel_span,
                    start=legs[0],
                    end=legs[-1],
                    waypoints=legs[1:-1],
                    style="spline",
                    floorZ=flight_floor(min(zs), max(zs), ground),
                    sourceId=f"stage:{spec.id}",
                )
            )
            t += travel_span
        else:
            lengths = [math.dist(a, b) for a, b in zip(legs, legs[1:], strict=False)]
            total = sum(lengths) or 1.0
            for (a, b), length in zip(zip(legs, legs[1:], strict=False), lengths, strict=True):
                dt = travel_span * (length / total)
                segments.append(
                    TrajectorySegment(
                        startTime=t,
                        duration=max(dt, 1e-3),
                        start=a,
                        end=b,
                        style="minjerk",
                        floorZ=flight_floor(a[2], b[2], ground),
                        sourceId=f"stage:{spec.id}",
                    )
                )
                t += dt
        if approach > 1e-6:
            segments.append(
                TrajectorySegment(
                    startTime=t,
                    duration=approach,
                    start=park,
                    end=entry_point,
                    style="minjerk",
                    floorZ=flight_floor(park[2], entry_point[2], ground),
                    sourceId=f"stage-approach:{spec.id}",
                )
            )

        # 3. the effect itself, as one continuous curve through the authored
        # samples. Flying it as a chain of separate legs would brake to a stop
        # at every sample and cost an order of magnitude more acceleration than
        # the choreography actually asks for.
        if len(path) >= 2:
            zs = [p[2] for p in path]
            segments.append(
                TrajectorySegment(
                    startTime=effect_start,
                    duration=max(effect_end - effect_start, 1e-3),
                    start=path[0],
                    end=path[-1],
                    waypoints=path[1:-1],
                    style="spline",
                    floorZ=flight_floor(min(zs), max(zs), ground),
                    sourceId=f"effect:{spec.id}",
                )
            )

        # 4. dark rejoin — the whole group leaves together, sized by the
        # slowest member, so the flight home keeps its separation bound. A
        # repair may slip one drone or route it around; the group plan
        # underneath stays intact and inspectable.
        exit_point: Vec3 = path[-1] if path else entry_point
        motion.returnFrom = exit_point
        return_start = max(effect_end, min(returnStart + motion.timeOffset, rejoin_time - 1e-3))
        if return_start > effect_end + 1e-6:
            segments.append(
                TrajectorySegment(
                    startTime=effect_end,
                    duration=return_start - effect_end,
                    start=exit_point,
                    end=exit_point,
                    style="hold",
                    floorZ=flight_floor(exit_point[2], exit_point[2], ground),
                    sourceId=f"stage-hold:{spec.id}",
                )
            )
        home = [exit_point, *motion.returnWaypoints, motion.returnTo]
        spans = [math.dist(a, b) for a, b in zip(home, home[1:], strict=False)]
        total_home = sum(spans) or 1.0
        window = max(rejoin_time - return_start, 1e-3)
        t = return_start
        for (a, b), length in zip(zip(home, home[1:], strict=False), spans, strict=True):
            dt = window * (length / total_home)
            segments.append(
                TrajectorySegment(
                    startTime=t,
                    duration=max(dt, 1e-3),
                    start=a,
                    end=b,
                    style="minjerk",
                    floorZ=flight_floor(a[2], b[2], ground),
                    sourceId=f"stage-rejoin:{spec.id}",
                )
            )
            t += dt
        program.trajectoryTrack.replace_window(window_start, rejoin_time, segments)

        # --- LIGHTING GENERATION ------------------------------------------
        blackout_start = motion.blackoutStart
        fade_from = motion.startTime - spec.blackoutLeadS
        if blackout_start is not None:
            fade_from = min(fade_from, blackout_start)
        fade_from = max(window_start, fade_from)
        rejoin_dark = max(effect_end, rejoin_time - spec.rejoinFadeS)

        keys: list[LightingKeyframe] = [
            LightingKeyframe(time=window_start, rgbLinear=hold_color, brightness=base_brightness),
            LightingKeyframe(time=fade_from, rgbLinear=hold_color, brightness=base_brightness),
            LightingKeyframe(time=motion.startTime, rgbLinear=hold_color, brightness=0.0),
        ]
        keys.extend(effect.lighting_keyframes(motion.targetIndex, ctx))
        keys.append(LightingKeyframe(time=effect_end, rgbLinear=rejoin_color, brightness=0.0))
        keys.append(LightingKeyframe(time=rejoin_dark, rgbLinear=rejoin_color, brightness=0.0))
        program.lightingTrack.replace_window(window_start, rejoin_time - 1e-6, keys)

        # --- ROLE TRACK ----------------------------------------------------
        program.roleTrack.replace_window(
            window_start,
            rejoin_time,
            [
                RoleSegment(
                    startTime=window_start,
                    endTime=motion.startTime,
                    roleType="FORMATION",
                    roleId=holding_formation_id,
                ),
                RoleSegment(
                    startTime=motion.startTime,
                    endTime=effect_start,
                    roleType="STAGING",
                    roleId=spec.id,
                    metadata={"purpose": "effect-entry", "effect": spec.id},
                ),
                RoleSegment(
                    startTime=effect_start,
                    endTime=effect_end,
                    roleType="EFFECT",
                    roleId=spec.id,
                    metadata={"particle": motion.targetIndex},
                ),
                RoleSegment(
                    startTime=effect_end,
                    endTime=rejoin_time,
                    roleType="STAGING",
                    roleId=rejoin_formation_id,
                    metadata={"purpose": "formation-rejoin"},
                ),
            ],
        )
        program.normalize()

    return rebuild
