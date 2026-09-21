from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.choreography.clock import ShowExecutionConfig
from app.choreography.scene import Scene

SCHEMA_VERSION = "0.2.0"
COMPILER_VERSION = "0.3.0"
COORDINATE_SYSTEM = "DSHOW_LOCAL_RH"
COLOR_SPACE = "linear-rgb"
CLOCK_DOMAIN = "show-monotonic"

Vec3 = tuple[float, float, float]
Rgb = tuple[float, float, float]
TransitionType = Literal[
    "direct", "morph", "stagger", "explode", "collapse", "orbit", "wave", "umap", "auto"
]
SamplingMode = Literal["outline", "fill", "feature", "surface", "silhouette", "wireframe", "audience"]


class LedProfile(BaseModel):
    type: Literal["RGB", "RGBW"] = "RGB"
    maximumBrightness: float = 1.0


class DroneProfile(BaseModel):
    name: str = "generic-show-drone"
    count: int = Field(default=250, ge=10, le=5000)
    radiusM: float = 0.2
    maxHorizontalSpeedMps: float = 8.0
    maxVerticalSpeedMps: float = 4.0
    maxAscentSpeedMps: float = 4.0
    maxDescentSpeedMps: float = 3.0
    maxAccelerationMps2: float = 3.0
    maxJerkMps3: float = 6.0
    minimumSeparationM: float = 2.5
    launchPitchM: float = 4.0
    trajectoryHz: float = 20.0
    lightingHz: float = 50.0
    led: LedProfile = Field(default_factory=LedProfile)


class AudienceCamera(BaseModel):
    position: Vec3 = (0.0, 90.0, 1.7)
    lookAt: Vec3 = (0.0, 0.0, 28.0)
    heightM: float = 1.7
    distanceM: float = 90.0
    fovDeg: float = 38.0


class VenueConfiguration(BaseModel):
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    altitudeDatum: Literal["local-z", "agl", "msl", "ellipsoid", "terrain"] = "local-z"
    groundZ: float = 0.0
    showHeadingRad: float = 0.0
    # Airspace the show is cleared for. This belongs to the site, not the
    # aircraft, and the validator reads it from here so the ceiling a formation
    # is built against is the same one it is later judged against.
    maxAltitudeM: float = 150.0
    radiusM: float = 400.0
    audience: AudienceCamera = Field(default_factory=AudienceCamera)


class SafetyProfile(BaseModel):
    navigationUncertaintyM: float = 0.3
    windAllowanceM: float = 0.2
    operatorMarginM: float = 0.3
    reactionTimeS: float = 0.25
    velocitySeparationFactor: float = 0.12
    launchPlacementErrorM: float = 0.15
    rtkUncertaintyM: float = 0.03
    gnssMode: Literal["rtk-fixed", "rtk-float", "gnss", "degraded"] = "rtk-fixed"
    takeoffSeparationM: float = 3.5


class Transform(BaseModel):
    translation: Vec3 = (0.0, 0.0, 25.0)
    rotationRad: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)


class FormationPoint(BaseModel):
    id: int
    position: Vec3
    color: Rgb = (1.0, 0.85, 0.7)
    # Visual weight of this point. A dragon eye is not an interior fill point.
    importance: float = 1.0
    sourceFeatureId: int | None = None
    featureId: str | None = None
    featureType: str | None = None
    featureMetadata: dict[str, float | int | str | bool] = Field(default_factory=dict)


class FormationGenerationSettings(BaseModel):
    mode: SamplingMode = "feature"
    widthM: float = 80.0
    heightM: float = 40.0
    depthM: float = 0.0
    seed: int = 1
    samplerVersion: int = 1
    packScale: float = 1.0
    # How far the packed artwork still pokes through the cleared ceiling after
    # being slid down as far as the floor allows. Non-zero means the shape is
    # taller than the airspace and needs a smaller drone count or a waiver.
    ceilingOvershootM: float = 0.0


class Formation(BaseModel):
    id: str
    name: str
    sourceAssetId: str
    role: Literal["launch", "artwork", "home"] = "artwork"
    points: list[FormationPoint] = Field(default_factory=list)
    transform: Transform = Field(default_factory=Transform)
    generationSettings: FormationGenerationSettings = Field(default_factory=FormationGenerationSettings)


class Asset(BaseModel):
    id: str
    name: str
    kind: Literal["svg", "png", "jpg", "glb", "obj", "stl", "text"]
    content: str


class Cue(BaseModel):
    id: str
    formationId: str
    startTime: float
    holdDuration: float
    phase: Literal["takeoff", "show", "rth", "landing"] = "show"


class DroneAssignment(BaseModel):
    droneId: int
    fromPointId: int
    toPointId: int


class Transition(BaseModel):
    id: str
    fromFormationId: str
    toFormationId: str
    startTime: float
    duration: float
    durationMode: Literal["auto", "manual"] = "auto"
    type: TransitionType = "morph"
    assignment: list[DroneAssignment] = Field(default_factory=list)
    trajectorySetId: str = ""


class AnimationClip(BaseModel):
    id: str
    name: str
    kind: Literal["rigid", "procedural", "sequence"] = "rigid"
    formationId: str
    cueOffset: float = 1.0
    startTime: float = 0.0
    duration: float = 4.0
    loop: bool = False
    motion: str = "backflip"
    amplitude: float = 1.0


class Timeline(BaseModel):
    duration: float = 0.0
    cues: list[Cue] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    animations: list[AnimationClip] = Field(default_factory=list)


class ShowSlot(BaseModel):
    droneId: int
    padIndex: int
    uavId: str | None = None


class CompilerNote(BaseModel):
    kind: Literal["safety", "art", "info"] = "info"
    message: str
    transitionId: str | None = None
    time: float | None = None


class ShowProject(BaseModel):
    version: str = "0.2.0"
    schemaVersion: str = SCHEMA_VERSION
    compilerVersion: str = COMPILER_VERSION
    id: str
    name: str
    coordinateSystem: str = COORDINATE_SYSTEM
    colorSpace: str = COLOR_SPACE
    clockDomain: Literal["show-monotonic", "utc", "gps", "unix", "smpte"] = "show-monotonic"
    showState: Literal["UNCOMPILED", "COMPILED", "VALIDATED", "ROBUSTNESS_TESTED", "EXPORTABLE"] = "UNCOMPILED"
    droneProfile: DroneProfile = Field(default_factory=DroneProfile)
    venue: VenueConfiguration = Field(default_factory=VenueConfiguration)
    assets: list[Asset] = Field(default_factory=list)
    formations: list[Formation] = Field(default_factory=list)
    timeline: Timeline = Field(default_factory=Timeline)
    # Artistic intent. Times are assigned by the compiler, not authored here.
    scenes: list[Scene] = Field(default_factory=list)
    # How the show is started, kept out of the immutable choreography.
    execution: ShowExecutionConfig = Field(default_factory=ShowExecutionConfig)
    safetyProfile: SafetyProfile = Field(default_factory=SafetyProfile)
    slots: list[ShowSlot] = Field(default_factory=list)
    compilerNotes: list[CompilerNote] = Field(default_factory=list)
    proximityViolations: list[Violation] = Field(default_factory=list)


class SafetyMeasurement(BaseModel):
    value: float
    limit: float
    passed: bool


class Violation(BaseModel):
    droneIds: list[int]
    time: float
    positions: list[Vec3]
    measured: float
    required: float
    severity: Literal["warn", "error"]
    message: str
    phase: Literal["takeoff", "show", "rth", "landing"] | None = None
    closingSpeedMps: float | None = None


class SafetyReport(BaseModel):
    passed: bool
    minimumSeparation: SafetyMeasurement
    maxHorizontalVelocity: SafetyMeasurement
    maxVerticalVelocity: SafetyMeasurement
    maxAcceleration: SafetyMeasurement
    maxJerk: SafetyMeasurement
    altitudeViolations: list[Violation] = Field(default_factory=list)
    geofenceViolations: list[Violation] = Field(default_factory=list)
    proximityViolations: list[Violation] = Field(default_factory=list)
    recommendedDuration: float | None = None


class GenerateFormationRequest(BaseModel):
    assetId: str
    name: str
    content: str
    kind: Literal["svg", "text", "glb", "obj", "stl"] = "svg"
    droneCount: int
    mode: SamplingMode = "feature"
    widthMeters: float = 80.0
    heightMeters: float = 40.0
    depthMeters: float = 0.0
    seed: int = 1
    color: Rgb | None = None
    # The show this asset is being converted for. Spacing and the cleared
    # ceiling are properties of the fleet and the site, not of the drawing,
    # and leaving them out is what let the preview disagree with the compile.
    # Optional so a bare request still works, but a caller that has a project
    # should always send them.
    droneProfile: DroneProfile | None = None
    safetyProfile: SafetyProfile | None = None
    venue: VenueConfiguration | None = None

    def context(self) -> tuple[DroneProfile, SafetyProfile, VenueConfiguration]:
        profile = self.droneProfile or DroneProfile(count=self.droneCount)
        if profile.count != self.droneCount:
            profile = profile.model_copy(update={"count": self.droneCount})
        return profile, self.safetyProfile or SafetyProfile(), self.venue or VenueConfiguration()


class SolveTransitionRequest(BaseModel):
    source: Formation
    target: Formation
    constraints: DroneProfile
    safety: SafetyProfile = Field(default_factory=SafetyProfile)
    style: TransitionType = "morph"
    duration: float | Literal["auto"] = "auto"
    seed: int = 1


class CompileShowRequest(BaseModel):
    project: ShowProject
    mode: Literal["preview", "full"] = "preview"


def capsule_radius(profile: DroneProfile, safety: SafetyProfile) -> float:
    extra = safety.rtkUncertaintyM if safety.gnssMode == "rtk-fixed" else 0.0
    return (
        profile.radiusM
        + safety.navigationUncertaintyM
        + safety.windAllowanceM
        + safety.operatorMarginM
        + extra
    )


def required_separation(profile: DroneProfile, safety: SafetyProfile, closing_speed: float = 0.0) -> float:
    return (
        profile.minimumSeparationM
        + profile.radiusM * 2
        + safety.navigationUncertaintyM
        + safety.windAllowanceM
        + safety.operatorMarginM
        + max(0.0, closing_speed) * safety.velocitySeparationFactor
    )
