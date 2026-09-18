# Digital twin, not a point simulator

Commanded XYZ is a desire, not the aircraft.

```
DESIRED TRAJECTORY
        ↓
aircraft dynamics
        + navigation uncertainty
        + clock uncertainty
        + wind
        + battery / performance
        + LED characteristics
        + venue geometry
        + audience perception
        ↓
WHAT ACTUALLY HAPPENS
```

v0.2 implements the first layer of that stack. The rest is in the schema so we do not have to retrofit later.

## In the compiler now

- **Launch grid** on `venue.groundZ` with `launchPitchM`. Takeoff and landing are their own phases. In-air spacing is not pad spacing.
- **Volumes.** Required separation includes airframe radius, nav/wind/operator, and a velocity term: `base + closingSpeed × velocitySeparationFactor`.
- **Capsules** in the viewport are larger than the rendered LED and grow with speed.
- **Between frames.** Closest approach is measured on the segment between samples, not only at sample instants.
- **Ascent ≠ descent.** `maxAscentSpeedMps` / `maxDescentSpeedMps`.
- **Jerk** is already a hard limit.
- **Deterministic** seed + `schemaVersion` + `compilerVersion` stored on the show.
- **Compiler notes** when duration or holds change. Safety edits are never silent.
- **Show state:** UNCOMPILED → COMPILED → VALIDATED → (later) ROBUSTNESS_TESTED → EXPORTABLE.
- **Slots** (`droneId`, `padIndex`, optional `uavId`). Formation point 17 is never permanently drone 17.
- **Importance** on every point for later degraded-fleet recompile.
- **Clock domain** `show-monotonic`. GPS/UTC/SMPTE are adapters.
- **Altitude datum** is explicit (`local-z` today).
- **Linear RGB** internally. sRGB only at the display.
- **Trajectory Hz ≠ lighting Hz.**

## Explicitly later (modeled, not simulated)

Clock-error Monte Carlo, RTK FIXED→FLOAT, launch placement injection, vehicle-response lag, battery envelopes, LED calibration, bloom/camera modes, audience-optimize, move-vs-black, wind gusts, lost timecode / point of no return.

Those belong on the twin, not in a prettier animation loop.
