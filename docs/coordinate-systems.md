# Coordinate systems

Canonical show space is **DSHOW_LOCAL_RH**.

| Axis | Meaning |
| --- | --- |
| +X | show right (audience right) |
| +Y | show forward (toward the audience) |
| +Z | up |

Right-handed. Units are SI: meters, seconds, radians, m/s, m/s², m/s³.

RGB is linear float `0.0–1.0` internally.

The show is authored in local coordinates. Venue (`latitude`, `longitude`, `altitude`, `altitudeDatum`, `groundZ`, `show_heading`) is applied only at export / site adaptation. `altitude` is meaningless without `altitudeDatum` (`local-z` | `agl` | `msl` | `ellipsoid` | `terrain`). Exporters convert into the target convention. RGB is linear internally.

## Three.js viewport

Three.js is Y-up. Mapping:

```
three.x = dshow.x
three.y = dshow.z
three.z = dshow.y
```

## Skybrush CSV

Skybrush samples are X right, Y forward, Z up in meters — the same as DSHOW_LOCAL_RH. Export writes `x_m, y_m, z_m` directly.

## VVIZ (visualization only)

VVIZ is X right, Y up, Z into the screen (away from the audience).

```
vviz.x = dshow.x
vviz.y = dshow.z
vviz.z = -dshow.y
```

VVIZ is labeled **visualization / interchange, not flight-ready**.
