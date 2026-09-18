"""Cost functions. Visual cost and physical cost are deliberately separate."""

from __future__ import annotations

import math

from pydantic import BaseModel

from app.choreography.audience import AudienceView

Vec3 = tuple[float, float, float]


class CostWeights(BaseModel):
    distance: float = 1.0
    verticalPenalty: float = 0.35
    featureImportance: float = 0.6
    roleChangePenalty: float = 1.5
    visibilityPenalty: float = 2.0
    topology: float = 0.05
    futureMovement: float = 0.7
    visualDisruption: float = 1.0


def visual_motion_cost(
    motion_magnitude: float,
    perceived_brightness: float,
    feature_importance: float,
    audience_visibility: float,
) -> float:
    """Dark motion approaches zero visual cost. Physical cost is unaffected."""
    return (
        max(0.0, motion_magnitude)
        * min(1.0, max(0.0, perceived_brightness))
        * min(1.0, max(0.0, feature_importance))
        * min(1.0, max(0.0, audience_visibility))
    )


def segment_visual_cost(
    start: Vec3,
    end: Vec3,
    brightness: float,
    importance: float,
    view: AudienceView | None = None,
) -> float:
    magnitude = math.dist(start, end)
    if view is None:
        visibility = 1.0
    else:
        visibility = 0.5 * (view.visibility(start) + view.visibility(end))
    return visual_motion_cost(magnitude, brightness, importance, visibility)


def physical_motion_cost(start: Vec3, end: Vec3) -> float:
    """Never modulated by lighting."""
    return math.dist(start, end)


def role_change_cost(from_role_id: str, to_role_id: str, weights: CostWeights) -> float:
    if not from_role_id or not to_role_id:
        return 0.0
    return 0.0 if from_role_id == to_role_id else weights.roleChangePenalty
