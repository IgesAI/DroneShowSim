# Safety engine

Drones are volumes, not points. A 2.5 m center gap can still be a collision once props, nav, wind, and tracking error are included.

```
capsule = radius + nav + wind + operator + (rtk if FIXED)

required(closing) = minimumSeparation
                  + 2 × radius
                  + nav + wind + operator
                  + max(0, closingSpeed) × velocitySeparationFactor
```

Takeoff/landing use `takeoffSeparationM` as a floor. Pad pitch is independent.

Validation samples min-jerk segments, then measures **closest approach on the segment between frames**. Two drones 4 m apart on frame N and N+1 still fail if their paths cross.

Warnings are causal: `D184 ↔ D319 at 12.482s during takeoff: 1.87m < 3.41m capsule (closing 6.2 m/s)`. Clicking one seeks the editor.

Ascent and descent limits are separate. Jerk is checked. Automatic duration changes are written to `compilerNotes`.
