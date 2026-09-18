"""Diff the browser's playback against the compiler's own track evaluation.

Needs apps/compiler-api on PYTHONPATH so `app` resolves. See dump.mts for the
two commands that produce the inputs. Expect residuals around 1e-5 m and 1e-8
on colour: the client packs frames into Float32Array, the compiler works in
double. Anything larger means the two evaluators have genuinely diverged and
the viewport is no longer showing the show that was certified.
"""

import json
import sys

from app.choreography.tracks import DroneProgram

demo = json.load(open(sys.argv[1], encoding="utf-8-sig"))
ts = json.load(open(sys.argv[2], encoding="utf-8"))

programs = {}
for raw in demo["choreography"]["programs"]:
    prog = DroneProgram.model_validate(raw)
    programs[prog.droneId] = prog

role_types = ts["roleTypes"]
max_pos = max_col = max_bri = 0.0
role_mismatch = 0
compared = 0

for ti, t in enumerate(ts["times"]):
    fr = ts["frames"][ti]
    for drone_id, prog in programs.items():
        p = prog.position(t)
        c = prog.color(t)
        b = prog.brightness(t)
        r = prog.role(t)
        for d in range(3):
            max_pos = max(max_pos, abs(float(p[d]) - fr["positions"][drone_id * 3 + d]))
            max_col = max(max_col, abs(float(c[d]) - fr["colors"][drone_id * 3 + d]))
        max_bri = max(max_bri, abs(float(b) - fr["brightness"][drone_id]))
        ts_role = role_types[fr["roles"][drone_id]]
        py_role = r.value if hasattr(r, "value") else str(r)
        if ts_role != py_role:
            role_mismatch += 1
        compared += 1

print(f"compared        {compared} drone-samples over {len(ts['times'])} times")
print(f"max |dposition| {max_pos:.3e} m")
print(f"max |dcolor|    {max_col:.3e}")
print(f"max |dbright|   {max_bri:.3e}")
print(f"role mismatches {role_mismatch}")
