# Lumina architecture

Project name: **Lumina**  
Format: **`.dshow`**  
Compiler: **`dshowc`**

```
ARTWORK → DRONE SHOW COMPILER → VENDOR ADAPTER → GCS → DRONES
```

The product owns the canonical show. Vendor systems are export targets.

## Layers (do not merge)

| Concept | Meaning |
| --- | --- |
| Formation | Where drones should be when an image is displayed |
| Animation | Timed operator on a formation (rigid / procedural / sequence) — never baked into points |
| Assignment | Which physical drone owns which target point |
| Trajectory | How that drone moves between targets (splines) |
| Light track | Color over time, independent of path |
| Show | Timeline of formations + transitions + animations |
| Export | Translation into another ecosystem |

Never permanently bind `formation point #17` to `drone #17`. Slots (`droneId` / pad / optional UAV serial) are the operational map.

Commanded position is not aircraft position. See `docs/digital-twin.md`.

Phases: takeoff → show → landing. Ground grid ≠ navigation-altitude proximity.

## Creative vs safety

Artistic solvers emit **candidate** trajectories. The safety compiler accepts, modifies, or rejects them. Art never bypasses physics.

## Process split

- **Browser:** UI, timeline, assets, viewport, playback, simple transforms
- **Python `dshowc`:** SVG/mesh/image sampling, assignment, min-jerk trajectories, collision, validation, exports

## Licensing

Skybrush Studio/Server are GPL-3.0-or-later. Do not copy their source. Implement adapters from documented formats only. See `docs/licensing.md`.

## AI

LLMs sit **above** the compiler and emit show-intent JSON. They do not compute trajectories.
