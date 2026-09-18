from __future__ import annotations

import math

from app.models import Formation, FormationGenerationSettings, FormationPoint, ShowSlot, Transform


def launch_grid_shape(count: int) -> tuple[int, int]:
    cols = max(1, math.ceil(math.sqrt(count * 1.7)))
    rows = max(1, math.ceil(count / cols))
    return cols, rows


def generate_launch_grid(
    count: int,
    pitch: float,
    ground_z: float = 0.0,
    formation_id: str = "frm_launch",
) -> tuple[Formation, list[ShowSlot]]:
    cols, rows = launch_grid_shape(count)
    pad_z = ground_z + 0.12
    points: list[FormationPoint] = []
    slots: list[ShowSlot] = []
    i = 0
    for r in range(rows):
        for c in range(cols):
            if i >= count:
                break
            x = (c - (cols - 1) / 2.0) * pitch
            y = ((rows - 1) / 2.0 - r) * pitch
            points.append(
                FormationPoint(
                    id=i,
                    position=(x, y, pad_z),
                    color=(0.45, 0.52, 0.72),
                    importance=0.15,
                    sourceFeatureId=i,
                )
            )
            slots.append(ShowSlot(droneId=i, padIndex=i))
            i += 1
    formation = Formation(
        id=formation_id,
        name="LAUNCH GRID",
        sourceAssetId="asset_launch",
        role="launch",
        points=points,
        transform=Transform(translation=(0.0, 0.0, 0.0)),
        generationSettings=FormationGenerationSettings(mode="feature", widthM=cols * pitch, heightM=0.2, depthM=rows * pitch, seed=1),
    )
    return formation, slots
