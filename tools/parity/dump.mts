// Half of the browser/compiler parity check: evaluate the compiled show with
// the client playback and write the frames out for compare.py to diff against
// the Python tracks. The canonical show is continuous, so the only thing that
// keeps the viewport honest is checking that both evaluators agree.
//
//   cd apps/compiler-api && export PYTHONPATH=$PWD
//   python -c "import json;from app.compile import solve_timeline;from app.choreography.pipeline import compile_choreography;from app.demo import dragon_project;p=solve_timeline(dragon_project(count=500,seed=1),mode='preview');print(json.dumps({'choreography':compile_choreography(p).model_dump()}))" > show.json
//   node --experimental-strip-types tools/parity/dump.mts show.json frames.json
//   python tools/parity/compare.py show.json frames.json
import { readFileSync, writeFileSync } from 'node:fs'
import { createChoreographyPlayback, ROLE_TYPES } from '../../packages/simulator/src/choreography.ts'

const raw = readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, '')
const playback = createChoreographyPlayback(JSON.parse(raw).choreography)

const times = [0, 5.5, 17.3, 42, 71.2, 95, 110.75, 117, 122.5, 129.9, 140, 200, 259]
const frames: unknown[] = []
let frame = undefined
for (const t of times) {
  frame = playback.evaluate(t, frame)
  frames.push({
    positions: Array.from(frame.positions),
    colors: Array.from(frame.colors),
    brightness: Array.from(frame.brightness),
    roles: Array.from(frame.roles),
  })
}
writeFileSync(process.argv[3], JSON.stringify({ times, roleTypes: ROLE_TYPES, count: playback.count, frames }))
console.log('dumped', times.length, 'frames x', playback.count, 'drones')
