import type {
  Choreography,
  DroneProgram,
  LightingKeyframe,
  RoleType,
  TrajectorySegment,
  Vec3,
} from '@lumina/schema'

/** Brightness at or below this reads as dark. Mirrors VISUAL_THRESHOLD in the compiler. */
export const VISUAL_THRESHOLD = 0.02

export function isVisuallyActive(brightness: number): boolean {
  return brightness > VISUAL_THRESHOLD
}

/** Role legend: `roles[i]` in a frame indexes this array. */
export const ROLE_TYPES = ['FORMATION', 'EFFECT', 'STAGING', 'RESERVE', 'TAKEOFF', 'RTH'] as const satisfies readonly RoleType[]

const RESERVE_CODE = ROLE_TYPES.indexOf('RESERVE')

export type ChoreographyFrame = {
  /** DSHOW_LOCAL_RH meters, 3 per drone, indexed by drone id. */
  positions: Float32Array
  /** Linear RGB, 3 per drone. Not premultiplied by brightness. */
  colors: Float32Array
  brightness: Float32Array
  /** Role codes into ROLE_TYPES. */
  roles: Uint8Array
  count: number
}

export type ChoreographyPlayback = {
  count: number
  duration: number
  evaluate: (time: number, out?: ChoreographyFrame) => ChoreographyFrame
  positionAt: (droneId: number, time: number) => Vec3
}

type Spline = { n: number; knots: Float64Array; moments: Float64Array }

type Segment = {
  startTime: number
  duration: number
  sx: number
  sy: number
  sz: number
  ex: number
  ey: number
  ez: number
  style: TrajectorySegment['style']
  floorZ: number
  spline: Spline | null
}

type Plan = {
  droneId: number
  segments: Segment[]
  segmentStarts: Float64Array
  keys: LightingKeyframe[]
  keyTimes: Float64Array
  roleEnds: Float64Array
  roleStarts: Float64Array
  roleCodes: Uint8Array
}

/**
 * Natural-cubic second derivatives at the knots, uniformly parameterised.
 * Constant per segment and expensive, so they are solved once up front.
 */
function buildSpline(segment: TrajectorySegment): Spline | null {
  if (segment.style !== 'spline' || segment.waypoints.length === 0) return null
  const points = [segment.start, ...segment.waypoints, segment.end]
  const n = points.length - 1
  const knots = new Float64Array((n + 1) * 3)
  for (let i = 0; i <= n; i++) {
    const p = points[i]
    knots[i * 3] = p[0]
    knots[i * 3 + 1] = p[1]
    knots[i * 3 + 2] = p[2]
  }
  const moments = new Float64Array((n + 1) * 3)
  if (n >= 2) {
    const h = 1 / n
    const hh = h * h
    const m = n - 1
    const rhs = new Float64Array(m)
    const c = new Float64Array(m)
    const r = new Float64Array(m)
    for (let d = 0; d < 3; d++) {
      for (let i = 1; i < n; i++) {
        rhs[i - 1] = (6 * (knots[(i - 1) * 3 + d] - 2 * knots[i * 3 + d] + knots[(i + 1) * 3 + d])) / hh
      }
      // Thomas algorithm on the tridiagonal (1, 4, 1) system.
      let beta = 4
      c[0] = 1 / beta
      r[0] = rhs[0] / beta
      for (let i = 1; i < m; i++) {
        beta = 4 - c[i - 1]
        c[i] = 1 / beta
        r[i] = (rhs[i] - r[i - 1]) / beta
      }
      for (let i = m - 1; i >= 0; i--) {
        r[i] = r[i] - c[i] * (i + 1 < m ? r[i + 1] : 0)
      }
      for (let i = 1; i < n; i++) moments[i * 3 + d] = r[i - 1]
    }
  }
  return { n, knots, moments }
}

function planProgram(program: DroneProgram): Plan {
  const source = [...program.trajectoryTrack.segments].sort((a, b) => a.startTime - b.startTime)
  const segments = source.map<Segment>((s) => ({
    startTime: s.startTime,
    duration: s.duration,
    sx: s.start[0],
    sy: s.start[1],
    sz: s.start[2],
    ex: s.end[0],
    ey: s.end[1],
    ez: s.end[2],
    style: s.style,
    floorZ: s.floorZ,
    spline: buildSpline(s),
  }))
  const segmentStarts = new Float64Array(segments.length)
  for (let i = 0; i < segments.length; i++) segmentStarts[i] = segments[i].startTime

  const keys = [...program.lightingTrack.keyframes].sort((a, b) => a.time - b.time)
  const keyTimes = new Float64Array(keys.length)
  for (let i = 0; i < keys.length; i++) keyTimes[i] = keys[i].time

  const roleSegments = [...program.roleTrack.segments].sort((a, b) => a.startTime - b.startTime)
  const roleStarts = new Float64Array(roleSegments.length)
  const roleEnds = new Float64Array(roleSegments.length)
  const roleCodes = new Uint8Array(roleSegments.length)
  for (let i = 0; i < roleSegments.length; i++) {
    roleStarts[i] = roleSegments[i].startTime
    roleEnds[i] = roleSegments[i].endTime
    const code = ROLE_TYPES.indexOf(roleSegments[i].roleType)
    roleCodes[i] = code < 0 ? RESERVE_CODE : code
  }

  return { droneId: program.droneId, segments, segmentStarts, keys, keyTimes, roleStarts, roleEnds, roleCodes }
}

/** Last index whose time is <= t, or -1. */
function search(times: Float64Array, t: number): number {
  let lo = 0
  let hi = times.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

/** Playback advances monotonically, so the previous index is usually still right. */
function seek(times: Float64Array, previous: number, t: number): number {
  const len = times.length
  if (previous >= 0 && previous < len && times[previous] <= t) {
    if (previous + 1 >= len || times[previous + 1] > t) return previous
    if (previous + 2 >= len || times[previous + 2] > t) return previous + 1
  }
  return search(times, t)
}

function writePosition(segment: Segment, t: number, out: Float32Array, o: number): void {
  const u = segment.duration <= 1e-9 ? 1 : Math.min(1, Math.max(0, (t - segment.startTime) / segment.duration))
  const spline = segment.spline
  if (spline) {
    const { n, knots, moments } = spline
    const x = u * n
    const i = Math.min(Math.floor(x), n - 1)
    const w = x - i
    const h2 = (1 / n) * (1 / n)
    const a = 1 - w
    const b = w
    const ka = i * 3
    const kb = ka + 3
    for (let d = 0; d < 3; d++) {
      const ma = moments[ka + d]
      const mb = moments[kb + d]
      out[o + d] =
        (ma * h2 * a * a * a) / 6 +
        (mb * h2 * b * b * b) / 6 +
        (knots[ka + d] - (ma * h2) / 6) * a +
        (knots[kb + d] - (mb * h2) / 6) * b
    }
    if (out[o + 2] < segment.floorZ) out[o + 2] = segment.floorZ
    return
  }
  const s = segment.style === 'hold' ? 0 : segment.style === 'linear' ? u : u * u * u * (10 + u * (-15 + 6 * u))
  out[o] = segment.sx + s * (segment.ex - segment.sx)
  out[o + 1] = segment.sy + s * (segment.ey - segment.sy)
  const z = segment.sz + s * (segment.ez - segment.sz)
  out[o + 2] = z < segment.floorZ ? segment.floorZ : z
}

function makeFrame(count: number): ChoreographyFrame {
  return {
    positions: new Float32Array(count * 3),
    colors: new Float32Array(count * 3),
    brightness: new Float32Array(count),
    roles: new Uint8Array(count).fill(RESERVE_CODE),
    count,
  }
}

export function createChoreographyPlayback(choreography: Choreography): ChoreographyPlayback {
  const plans = choreography.programs.map(planProgram)
  let maxId = -1
  for (const plan of plans) maxId = Math.max(maxId, plan.droneId)
  const count = maxId + 1

  const segmentCursor = new Int32Array(plans.length).fill(-1)
  const keyCursor = new Int32Array(plans.length).fill(-1)
  const roleCursor = new Int32Array(plans.length).fill(-1)
  const scratch = new Float32Array(3)
  const owned = makeFrame(count)

  const evaluate = (time: number, out?: ChoreographyFrame): ChoreographyFrame => {
    const frame = out && out.positions.length === count * 3 && out.brightness.length === count ? out : owned
    const { positions, colors, brightness, roles } = frame
    const t = Math.max(0, time)

    for (let p = 0; p < plans.length; p++) {
      const plan = plans[p]
      const i = plan.droneId
      const o = i * 3

      const segments = plan.segments
      if (segments.length > 0) {
        let s = seek(plan.segmentStarts, segmentCursor[p], t)
        if (s < 0) s = 0
        segmentCursor[p] = s
        writePosition(segments[s], t, positions, o)
      } else {
        positions[o] = 0
        positions[o + 1] = 0
        positions[o + 2] = 0
      }

      const keys = plan.keys
      if (keys.length === 0) {
        brightness[i] = 1
        colors[o] = 1
        colors[o + 1] = 1
        colors[o + 2] = 1
      } else {
        const k = seek(plan.keyTimes, keyCursor[p], t)
        keyCursor[p] = k
        let a: LightingKeyframe
        let b: LightingKeyframe
        let u = 0
        if (k < 0) {
          a = keys[0]
          b = a
        } else if (k >= keys.length - 1) {
          a = keys[keys.length - 1]
          b = a
        } else {
          a = keys[k]
          b = keys[k + 1]
          if (a.interpolation === 'step') {
            b = a
          } else {
            const span = b.time - a.time
            u = span <= 1e-9 ? 0 : Math.min(1, Math.max(0, (t - a.time) / span))
          }
        }
        const lit = a.brightness + u * (b.brightness - a.brightness)
        brightness[i] = lit < 0 ? 0 : lit > 1 ? 1 : lit
        colors[o] = a.rgbLinear[0] + u * (b.rgbLinear[0] - a.rgbLinear[0])
        colors[o + 1] = a.rgbLinear[1] + u * (b.rgbLinear[1] - a.rgbLinear[1])
        colors[o + 2] = a.rgbLinear[2] + u * (b.rgbLinear[2] - a.rgbLinear[2])
      }

      let code = RESERVE_CODE
      let r = seek(plan.roleStarts, roleCursor[p], t + 1e-9)
      if (r >= 0) roleCursor[p] = r
      while (r >= 0) {
        if (t < plan.roleEnds[r] + 1e-9) {
          code = plan.roleCodes[r]
          break
        }
        r -= 1
      }
      roles[i] = code
    }

    return frame
  }

  const positionAt = (droneId: number, time: number): Vec3 => {
    const plan = plans.find((x) => x.droneId === droneId)
    if (!plan || plan.segments.length === 0) return [0, 0, 0]
    const t = Math.max(0, time)
    const s = Math.max(0, search(plan.segmentStarts, t))
    writePosition(plan.segments[s], t, scratch, 0)
    return [scratch[0], scratch[1], scratch[2]]
  }

  return { count, duration: choreography.duration, evaluate, positionAt }
}
