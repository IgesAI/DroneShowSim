# Animations

An animation is not a formation and not a transition.

| Layer | Job |
| --- | --- |
| Formation | Static N-point artwork |
| Animation | Time-varying operator on a formation |
| Transition | Assignment + path between two formations |
| Safety | Validates the *resulting* motion |

Never bake a backflip into the formation points. The motorcycle stays a motorcycle. The backflip is a clip on top of it.

## Kinds

**Rigid.** The whole cloud shares one transform around its centroid.

- `backflip` — 360° pitch about +X (audience-right)
- `orbit` — yaw about +Z
- `advance` — translate toward the audience (+Y)
- `yaw` — in-place heading spin

**Procedural.** Per-point offsets that keep topology.

- `wave` / `flap` / `pulse`

**Sequence (later).** Sample a GLB/video at several times into N points each, then spline. Same drone count. Safety still runs.

Imported skeletal animation becomes a sequence of formations with *identity* assignment (point 17 stays 17) because the mesh already owns correspondence.

## Timeline

```
FORMATION   [LOGO]────────[MOTORCYCLE]────────[COBRA]
TRANSITION         [MORPH]            [MORPH]
ANIMATION               [BACKFLIP]
```

`cueOffset` is authored relative to the hold. Compile writes absolute `startTime` after cues are packed.

If the clip is longer than the hold, the compiler extends the hold. It does not silently crop the trick.

## Safety

Candidate animated poses are sampled at validation rate. A 4s backflip that needs 7s at `amax` is infeasible — same UX as a short morph.

Artistic motion never bypasses the safety compiler.

## Color

Each formation point already has RGB. SVG stroke/fill (and `style=`) is sampled per path — a red cobra and a cream motorcycle stay those colors. Transitions lerp color with the assignment.

`chroma` is a color operator: it pulses brightness of the existing per-point colors. It does not replace a light track. Dedicated color keyframes (strobe, hue sweeps, per-drone lighting cues) are a later track, same rule as motion: never bake lights into the formation points.

Raster images (PNG/JPG) need a fill sampler. Until then, import SVG artwork if you need multi-color.
