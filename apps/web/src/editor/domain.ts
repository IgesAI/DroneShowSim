import { requiredSeparationM, type Formation, type ShowProject, type Transition, type Violation } from '@lumina/schema'

export type CompilerPhase =
  | 'DRAFT'
  | 'GENERATED'
  | 'COMPILED'
  | 'VALIDATED'
  | 'ROBUSTNESS CHECKED'
  | 'EXPORT READY'

export type DroneBudget = {
  available: number
  assigned: number
  structural: number
  detail: number
  unused: number
}

export type Envelope = {
  width: number
  depth: number
  height: number
  radius: number
}

export type TransitionStats = {
  meanM: number
  maxM: number
  vmax: number
  crossings: number
  minSep: number
  outerDeltaM: number
  extraS: number
}

export function compilerPhase(args: {
  project: ShowProject | null
  compiling: boolean
  dirty: boolean
  violations: Violation[]
}): { phase: CompilerPhase; tone: 'idle' | 'accent' | 'warn' | 'ok' } {
  const { project, compiling, dirty, violations } = args
  if (compiling) return { phase: 'GENERATED', tone: 'accent' }
  if (!project || project.formations.length === 0) return { phase: 'DRAFT', tone: 'idle' }
  if (dirty || project.showState === 'UNCOMPILED') return { phase: 'DRAFT', tone: 'warn' }
  const errors = violations.some((v) => v.severity === 'error')
  if (project.showState === 'ROBUSTNESS_TESTED') return { phase: 'ROBUSTNESS CHECKED', tone: errors ? 'warn' : 'ok' }
  if (project.showState === 'EXPORTABLE' || (project.showState === 'VALIDATED' && !errors)) {
    return { phase: 'EXPORT READY', tone: 'ok' }
  }
  if (project.showState === 'VALIDATED') return { phase: 'VALIDATED', tone: errors ? 'warn' : 'ok' }
  return { phase: 'COMPILED', tone: 'ok' }
}

export function flaggedDrones(violations: Violation[]): Set<number> {
  const ids = new Set<number>()
  for (const v of violations) {
    if (v.severity === 'error') for (const id of v.droneIds) ids.add(id)
  }
  return ids
}

export function droneBudget(formation: Formation | undefined, available: number): DroneBudget {
  const pts = formation?.points ?? []
  const structural = pts.filter((p) => p.importance >= 0.61).length
  const detail = pts.length - structural
  return {
    available,
    assigned: pts.length,
    structural,
    detail,
    unused: Math.max(0, available - pts.length),
  }
}

export function formationEnvelope(formation: Formation | undefined): Envelope | null {
  const pts = formation?.points
  if (!pts?.length) return null
  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity
  let cx = 0
  let cy = 0
  let cz = 0
  for (const p of pts) {
    const [x, y, z] = p.position
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    minZ = Math.min(minZ, z)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
    maxZ = Math.max(maxZ, z)
    cx += x
    cy += y
    cz += z
  }
  const inv = 1 / pts.length
  cx *= inv
  cy *= inv
  cz *= inv
  let radius = 0
  for (const p of pts) {
    radius = Math.max(radius, Math.hypot(p.position[0] - cx, p.position[1] - cy, p.position[2] - cz))
  }
  return {
    width: maxX - minX,
    depth: maxY - minY,
    height: maxZ - minZ,
    radius,
  }
}

export function formationQuality(formation: Formation, available: number, reqSep: number) {
  const n = formation.points.length
  const pack = Math.max(formation.generationSettings.packScale ?? 1, 1)
  let occluded = 0
  for (let i = 0; i < n; i++) {
    const a = formation.points[i]
    if (!a) continue
    let best = Infinity
    for (let j = 0; j < n; j++) {
      if (i === j) continue
      const b = formation.points[j]
      if (!b) continue
      const d = Math.hypot(a.position[0] - b.position[0], a.position[2] - b.position[2])
      if (d < best) best = d
    }
    if (best < reqSep * 0.35) occluded += 1
  }
  return {
    utilization: n / Math.max(available, 1),
    silhouette: 1 / pack,
    occluded,
    occlusion: 1 - occluded / Math.max(n, 1),
  }
}

function segmentsCross(a0: number[], a1: number[], b0: number[], b1: number[]) {
  const d = (a1[0] - a0[0]) * (b1[1] - b0[1]) - (a1[1] - a0[1]) * (b1[0] - b0[0])
  if (Math.abs(d) < 1e-8) return false
  const t = ((b0[0] - a0[0]) * (b1[1] - b0[1]) - (b0[1] - a0[1]) * (b1[0] - b0[0])) / d
  const u = ((b0[0] - a0[0]) * (a1[1] - a0[1]) - (b0[1] - a0[1]) * (a1[0] - a0[0])) / d
  return t > 0.02 && t < 0.98 && u > 0.02 && u < 0.98
}

export function transitionStats(
  project: ShowProject,
  tr: Transition,
): TransitionStats | null {
  const from = project.formations.find((f) => f.id === tr.fromFormationId)
  const to = project.formations.find((f) => f.id === tr.toFormationId)
  if (!from || !to || !tr.assignment.length) return null
  const segs: { a: number[]; b: number[]; d: number }[] = []
  let sum = 0
  let maxM = 0
  for (const asg of tr.assignment) {
    const a = from.points[asg.fromPointId] ?? from.points[asg.droneId]
    const b = to.points[asg.toPointId] ?? to.points[asg.droneId]
    if (!a || !b) continue
    const d = Math.hypot(b.position[0] - a.position[0], b.position[1] - a.position[1], b.position[2] - a.position[2])
    sum += d
    maxM = Math.max(maxM, d)
    segs.push({ a: [a.position[0], a.position[1]], b: [b.position[0], b.position[1]], d })
  }
  if (!segs.length) return null
  let crossings = 0
  const cap = Math.min(segs.length, 80)
  for (let i = 0; i < cap; i++) {
    for (let j = i + 1; j < cap; j++) {
      const A = segs[i]
      const B = segs[j]
      if (A && B && segmentsCross(A.a, A.b, B.a, B.b)) crossings += 1
    }
  }
  let minSep = Infinity
  for (let i = 0; i < to.points.length; i++) {
    const p = to.points[i]
    if (!p) continue
    for (let j = i + 1; j < to.points.length; j++) {
      const q = to.points[j]
      if (!q) continue
      minSep = Math.min(minSep, Math.hypot(p.position[0] - q.position[0], p.position[1] - q.position[1], p.position[2] - q.position[2]))
    }
  }
  const fromEnv = formationEnvelope(from)
  const toEnv = formationEnvelope(to)
  const outerDeltaM = (toEnv?.radius ?? 0) - (fromEnv?.radius ?? 0)
  const limit = project.droneProfile.maxHorizontalSpeedMps
  const needed = maxM / Math.max(limit, 0.1)
  return {
    meanM: sum / segs.length,
    maxM,
    vmax: (maxM / Math.max(tr.duration, 1e-3)) * 1.875,
    crossings,
    minSep: Number.isFinite(minSep) ? minSep : 0,
    outerDeltaM,
    extraS: Math.max(0, needed - tr.duration),
  }
}

export function nearestNeighbor(positions: Float32Array, i: number): number {
  const n = positions.length / 3
  const ax = positions[i * 3] ?? 0
  const ay = positions[i * 3 + 1] ?? 0
  const az = positions[i * 3 + 2] ?? 0
  let best = Infinity
  for (let j = 0; j < n; j++) {
    if (j === i) continue
    const d = Math.hypot(ax - (positions[j * 3] ?? 0), ay - (positions[j * 3 + 1] ?? 0), az - (positions[j * 3 + 2] ?? 0))
    if (d < best) best = d
  }
  return Number.isFinite(best) ? best : 0
}

export function showClock(seconds: number) {
  const ms = Math.max(0, Math.round(seconds * 1000))
  const milli = ms % 1000
  const s = Math.floor(ms / 1000) % 60
  const m = Math.floor(ms / 60000)
  const pad = (n: number, w = 2) => String(n).padStart(w, '0')
  return `T+${pad(m)}:${pad(s)}.${pad(milli, 3)}`
}

export function requiredSep(project: ShowProject) {
  return requiredSeparationM(project.droneProfile, project.safetyProfile)
}

export function droneLabel(id: number) {
  return `D${String(id).padStart(3, '0')}`
}
