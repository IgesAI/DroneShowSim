"""Temporal choreography.

Physical drone motion, visual appearance, temporal role and formation
membership are separate concepts. This package keeps them separate:

- `tracks`   independent trajectory / lighting / role tracks per drone
- `clock`    monotonic show time and the execution state machine
- `scene`    artistic intent, compiled into motion later
- `effects`  generic time-varying formation generators
- `staging`  dark repositioning with unchanged physical constraints
- `pipeline` the compiler that turns intent into per-drone programs

Submodules are imported directly to avoid an import cycle with `app.models`.
"""
