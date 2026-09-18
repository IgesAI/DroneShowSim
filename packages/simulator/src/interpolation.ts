import type { Vec3 } from '@lumina/schema'

/** Minimum-jerk ease: zero velocity and acceleration at both ends. */
export function minJerk(u: number): number {
  const x = Math.min(1, Math.max(0, u))
  return x * x * x * (10 + x * (-15 + 6 * x))
}

export function minJerkVelocityScale(u: number): number {
  const x = Math.min(1, Math.max(0, u))
  return 30 * x * x - 60 * x * x * x + 30 * x * x * x * x
}

export function lerp3(a: Vec3, b: Vec3, t: number): Vec3 {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ]
}

const PAD_Z = 0.12
const AIR_FLOOR_Z = 1.0

export function flightFloor(z0: number, z1 = z0): number {
  const lo = Math.min(z0, z1)
  return lo >= -1e-6 && lo <= PAD_Z + 0.25 ? 0 : AIR_FLOOR_Z
}

export function evaluateSegment(from: Vec3, to: Vec3, u: number, style: string): Vec3 {
  const s = style === 'direct' ? u : minJerk(u)
  if (style === 'explode') {
    const mid: Vec3 = [
      (from[0] + to[0]) / 2 + from[0] * 0.35,
      (from[1] + to[1]) / 2,
      (from[2] + to[2]) / 2 + 8,
    ]
    const o = 1 - s
    const z = from[2] * o * o + mid[2] * 2 * o * s + to[2] * s * s
    return [
      from[0] * o * o + mid[0] * 2 * o * s + to[0] * s * s,
      from[1] * o * o + mid[1] * 2 * o * s + to[1] * s * s,
      Math.max(z, flightFloor(from[2], to[2])),
    ]
  }
  if (style === 'orbit') {
    const mx = (from[0] + to[0]) / 2
    const my = (from[1] + to[1]) / 2
    const a0 = Math.atan2(from[1] - my, from[0] - mx)
    const a1 = Math.atan2(to[1] - my, to[0] - mx)
    let da = a1 - a0
    if (da > Math.PI) da -= Math.PI * 2
    else if (da < -Math.PI) da += Math.PI * 2
    const r0 = Math.hypot(from[0] - mx, from[1] - my)
    const r1 = Math.hypot(to[0] - mx, to[1] - my)
    if (r0 < 1e-6 && r1 < 1e-6) {
      const p = lerp3(from, to, s)
      return [p[0], p[1], Math.max(p[2], flightFloor(from[2], to[2]))]
    }
    const r = r0 + (r1 - r0) * s
    const a = a0 + da * s
    const p: Vec3 = [mx + Math.cos(a) * r, my + Math.sin(a) * r, from[2] + (to[2] - from[2]) * s]
    p[2] = Math.max(p[2], flightFloor(from[2], to[2]))
    return p
  }
  if (style === 'wave') {
    const p = lerp3(from, to, s)
    return [p[0], p[1], Math.max(p[2] + Math.sin(s * Math.PI) * 6, flightFloor(from[2], to[2]))]
  }
  const p = lerp3(from, to, s)
  return [p[0], p[1], Math.max(p[2], flightFloor(from[2], to[2]))]
}

/** DSHOW_LOCAL_RH → Three.js (Y-up, camera looks down -Z). */
export function toThree(p: Vec3): Vec3 {
  return [p[0], p[2], p[1]]
}

export function applyMotion(
  p: Vec3,
  centroid: Vec3,
  motion: string,
  u: number,
  amplitude: number,
): Vec3 {
  const e = minJerk(u)
  const x = p[0] - centroid[0]
  const y = p[1] - centroid[1]
  const z = p[2] - centroid[2]
  const floor = p[2] >= -1e-6 && p[2] <= PAD_Z + 0.25 ? 0 : AIR_FLOOR_Z
  const keepUp = (q: Vec3): Vec3 => [q[0], q[1], Math.max(q[2], floor)]
  if (motion === 'backflip') {
    const a = e * Math.PI * 2
    return keepUp([p[0], centroid[1] + y * Math.cos(a) - z * Math.sin(a), centroid[2] + y * Math.sin(a) + z * Math.cos(a)])
  }
  if (motion === 'orbit' || motion === 'yaw') {
    const a = e * Math.PI * 2
    return [centroid[0] + x * Math.cos(a) - y * Math.sin(a), centroid[1] + x * Math.sin(a) + y * Math.cos(a), p[2]]
  }
  if (motion === 'advance') {
    return [p[0], p[1] + e * 18 * amplitude, p[2]]
  }
  if (motion === 'wave') {
    return keepUp([p[0], p[1], p[2] + Math.sin(u * Math.PI * 2 + p[0] * 0.12) * 4 * amplitude])
  }
  if (motion === 'flap') {
    const wing = Math.sign(x) || 1
    return keepUp([p[0], p[1], p[2] + Math.sin(u * Math.PI * 2) * 6 * amplitude * Math.abs(x) * 0.04 * wing])
  }
  if (motion === 'pulse') {
    const s = 1 + Math.sin(u * Math.PI * 2) * 0.12 * amplitude
    return keepUp([centroid[0] + x * s, centroid[1] + y * s, centroid[2] + z * s])
  }
  return keepUp(p)
}

export function applyColor(color: Vec3, motion: string, u: number, amplitude: number): Vec3 {
  if (motion !== 'chroma') return color
  const s = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(u * Math.PI * 2)) * amplitude
  return [
    Math.min(1, color[0] * s),
    Math.min(1, color[1] * s),
    Math.min(1, color[2] * s),
  ]
}
