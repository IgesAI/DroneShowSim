"""Scenes are artistic intent. They do not contain baked per-drone motion."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SceneKind = Literal["TAKEOFF", "FORMATION", "EFFECT", "RTH", "LANDING", "INTERLUDE"]


class ResourceRequest(BaseModel):
    """An effect asks for capacity, never for specific drone IDs."""

    preferred: int = 32
    minimum: int = 8
    maximum: int = 64
    # An effect authored for a 500-drone show must not eat a 100-drone one.
    # Counts are absolute, so without this the same dragon-breath spec takes
    # 13% of one fleet and 64% of the other, and the dragon stops being a
    # dragon.
    maxFleetFraction: float = 0.2
    # Features worth more than this to the audience are not for sale. Cost
    # alone cannot express that: the drones nearest a dragon's mouth are the
    # jaw and the eye, so an allocator weighing travel against importance will
    # always take the face first. The ceiling is raised, and reported, only if
    # the effect cannot otherwise reach its minimum.
    maxBorrowImportance: float = 0.55

    def clamp(self, available: int) -> int:
        return max(0, min(self.maximum, min(self.preferred, available)))

    def satisfied_by(self, allocated: int) -> bool:
        return allocated >= self.minimum

    def capped(self, capacity: int, fleet: int | None = None) -> "ResourceRequest":
        """Narrow the request to what the geometry and the fleet can spare."""
        ceiling = max(0, capacity)
        if fleet is not None and self.maxFleetFraction > 0:
            ceiling = min(ceiling, max(1, int(fleet * self.maxFleetFraction)))
        return self.model_copy(
            update={
                "preferred": min(self.preferred, ceiling),
                "minimum": min(self.minimum, ceiling),
                "maximum": min(self.maximum, ceiling),
            }
        )


class SceneLighting(BaseModel):
    mode: Literal["formation", "blackout", "uniform"] = "formation"
    baseBrightness: float = 1.0
    rgbLinear: tuple[float, float, float] | None = None
    fadeInS: float = 0.0
    fadeOutS: float = 0.0


class SceneTransition(BaseModel):
    style: str = "morph"
    durationS: float | None = None
    durationMode: Literal["auto", "manual"] = "auto"
    allowDarkStaging: bool = True


AnchorMode = Literal["explicit", "formation-extreme", "formation-centroid"]


class EffectSpec(BaseModel):
    id: str
    name: str = ""
    type: str = "dragon-breath"
    resources: ResourceRequest = Field(default_factory=ResourceRequest)
    startOffset: float = 0.0
    duration: float = 4.5
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int = 1

    # Anchors resolve against generated geometry, so no coordinates are baked
    # into authoring data and no drone ids are named.
    anchorMode: AnchorMode = "explicit"
    anchorPosition: tuple[float, float, float] | None = None
    anchorFormationId: str | None = None
    anchorAxis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    anchorOffset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchorImportanceMin: float = 0.0

    # Dark staging controls.
    blackoutLeadS: float = 1.2
    maxStagingLeadS: float = 14.0
    stagingMarginS: float = 0.5
    rejoinFadeS: float = 0.6
    # 0 lets the compiler derive the corridor depth from the formation's own
    # thickness and the required separation.
    corridorDepthM: float = 0.0


class Scene(BaseModel):
    """Authoring is time-free where possible: the compiler assigns startTime.

    An EFFECT scene hangs off a host formation scene by `hostFormationId` and
    `hostOffsetS`, so retiming the show does not invalidate the intent.
    """

    id: str
    name: str
    kind: SceneKind = "FORMATION"
    startTime: float = 0.0
    duration: float = 0.0
    formationIds: list[str] = Field(default_factory=list)
    effects: list[EffectSpec] = Field(default_factory=list)
    lighting: SceneLighting = Field(default_factory=SceneLighting)
    transition: SceneTransition = Field(default_factory=SceneTransition)
    hostFormationId: str | None = None
    hostOffsetS: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def endTime(self) -> float:
        return self.startTime + self.duration

    def contains(self, t: float) -> bool:
        return self.startTime - 1e-9 <= t < self.endTime + 1e-9


def scene_at(scenes: list[Scene], t: float) -> Scene | None:
    for scene in sorted(scenes, key=lambda s: s.startTime):
        if scene.contains(t):
            return scene
    return None


def next_formation_scene(scenes: list[Scene], after: float) -> Scene | None:
    for scene in sorted(scenes, key=lambda s: s.startTime):
        if scene.startTime >= after - 1e-9 and scene.kind in {"FORMATION", "LANDING", "RTH"}:
            return scene
    return None
