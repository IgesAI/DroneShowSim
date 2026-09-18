import type { Color, Vec3, Volume } from './types'

export function vec(x: number, y: number, z: number): Vec3 {
  return { x, y, z }
}

export function add(a: Vec3, b: Vec3): Vec3 {
  return { x: a.x + b.x, y: a.y + b.y, z: a.z + b.z }
}

export function sub(a: Vec3, b: Vec3): Vec3 {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z }
}

export function scale(a: Vec3, s: number): Vec3 {
  return { x: a.x * s, y: a.y * s, z: a.z * s }
}

export function lerp(a: Vec3, b: Vec3, t: number): Vec3 {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    z: a.z + (b.z - a.z) * t,
  }
}

export function dist(a: Vec3, b: Vec3): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)
}

export function dist2(a: Vec3, b: Vec3): number {
  const dx = a.x - b.x
  const dy = a.y - b.y
  const dz = a.z - b.z
  return dx * dx + dy * dy + dz * dz
}

export function length(a: Vec3): number {
  return Math.hypot(a.x, a.y, a.z)
}

export function normalize(a: Vec3): Vec3 {
  const l = length(a) || 1
  return scale(a, 1 / l)
}

export function centroid(points: Vec3[]): Vec3 {
  const c = vec(0, 0, 0)
  if (points.length === 0) return c
  for (const p of points) {
    c.x += p.x
    c.y += p.y
    c.z += p.z
  }
  return scale(c, 1 / points.length)
}

export function rotateY(p: Vec3, angle: number, pivot: Vec3): Vec3 {
  const x = p.x - pivot.x
  const z = p.z - pivot.z
  const c = Math.cos(angle)
  const s = Math.sin(angle)
  return { x: pivot.x + x * c - z * s, y: p.y, z: pivot.z + x * s + z * c }
}

export function rotateX(p: Vec3, angle: number, pivot: Vec3): Vec3 {
  const y = p.y - pivot.y
  const z = p.z - pivot.z
  const c = Math.cos(angle)
  const s = Math.sin(angle)
  return { x: p.x, y: pivot.y + y * c - z * s, z: pivot.z + y * s + z * c }
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

export function saturate(v: number): number {
  return clamp(v, 0, 1)
}

export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

export function smoothstep(t: number): number {
  const x = saturate(t)
  return x * x * (3 - 2 * x)
}

export function bezier(a: Vec3, c: Vec3, b: Vec3, t: number): Vec3 {
  const u = 1 - t
  return add(add(scale(a, u * u), scale(c, 2 * u * t)), scale(b, t * t))
}

export function hexToColor(hex: string): Color {
  const n = hex.replace('#', '')
  const v = n.length === 3
    ? n.split('').map((ch) => parseInt(ch + ch, 16))
    : [n.slice(0, 2), n.slice(2, 4), n.slice(4, 6)].map((ch) => parseInt(ch, 16))
  return { r: (v[0] ?? 255) / 255, g: (v[1] ?? 255) / 255, b: (v[2] ?? 255) / 255 }
}

export function lerpColor(a: Color, b: Color, t: number): Color {
  return {
    r: a.r + (b.r - a.r) * t,
    g: a.g + (b.g - a.g) * t,
    b: a.b + (b.b - a.b) * t,
  }
}

export function uid(prefix = 'id'): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`
}

export function fitToVolume(points: Vec3[], volume: Volume, flat = false): Vec3[] {
  if (points.length === 0) return points
  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    minZ = Math.min(minZ, p.z)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
    maxZ = Math.max(maxZ, p.z)
  }
  const bw = Math.max(1e-4, maxX - minX)
  const bh = Math.max(1e-4, maxY - minY)
  const bd = Math.max(1e-4, maxZ - minZ)
  const sx = volume.width / bw
  const sy = volume.height / bh
  const sz = volume.depth / (flat ? Math.max(bd, volume.depth) : bd)
  const s = Math.min(sx, sy, flat ? sx : sz) * 0.88
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  const cz = (minZ + maxZ) / 2
  const midY = volume.y0 + volume.height * 0.52
  return points.map((p) => ({
    x: (p.x - cx) * s,
    y: (p.y - cy) * s + midY,
    z: flat ? (p.z - cz) * Math.min(s, 2) : (p.z - cz) * s,
  }))
}

export function farthestPointSample(candidates: Vec3[], n: number): Vec3[] {
  if (candidates.length === 0) return []
  if (candidates.length <= n) {
    const out = candidates.slice()
    let i = 0
    while (out.length < n) {
      const src = candidates[i % candidates.length]!
      out.push({
        x: src.x + (Math.random() - 0.5) * 0.4,
        y: src.y + (Math.random() - 0.5) * 0.4,
        z: src.z + (Math.random() - 0.5) * 0.15,
      })
      i += 1
    }
    return out
  }
  const picked: Vec3[] = [candidates[Math.floor(Math.random() * candidates.length)]!]
  const minD = new Float64Array(candidates.length)
  for (let i = 0; i < candidates.length; i++) minD[i] = dist2(candidates[i]!, picked[0]!)
  while (picked.length < n) {
    let best = 0
    let bestD = -1
    for (let i = 0; i < candidates.length; i++) {
      if (minD[i]! > bestD) {
        bestD = minD[i]!
        best = i
      }
    }
    const next = candidates[best]!
    picked.push(next)
    for (let i = 0; i < candidates.length; i++) {
      const d = dist2(candidates[i]!, next)
      if (d < minD[i]!) minD[i] = d
    }
  }
  return picked
}

export function weightedPick(candidates: Vec3[], weights: number[], count: number): Vec3[] {
  const pool: Vec3[] = []
  const maxW = Math.max(...weights, 1e-6)
  for (let i = 0; i < candidates.length; i++) {
    const copies = 1 + Math.round((weights[i]! / maxW) * 3)
    for (let k = 0; k < copies; k++) pool.push(candidates[i]!)
  }
  return farthestPointSample(pool, count)
}

export function separatePoints(points: Vec3[], minSpacing: number, iterations = 10): Vec3[] {
  const out = points.map((p) => ({ ...p }))
  const min2 = minSpacing * minSpacing
  for (let iter = 0; iter < iterations; iter++) {
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const d2 = dist2(out[i]!, out[j]!)
        if (d2 >= min2) continue
        if (d2 < 1e-8) {
          out[j]!.x += (Math.random() - 0.5) * minSpacing * 0.4
          out[j]!.y += (Math.random() - 0.5) * minSpacing * 0.4
          continue
        }
        const d = Math.sqrt(d2)
        const push = ((minSpacing - d) / d) * 0.35
        const dx = (out[i]!.x - out[j]!.x) * push
        const dy = (out[i]!.y - out[j]!.y) * push
        const dz = (out[i]!.z - out[j]!.z) * push
        out[i]!.x += dx
        out[i]!.y += dy
        out[i]!.z += dz
        out[j]!.x -= dx
        out[j]!.y -= dy
        out[j]!.z -= dz
      }
    }
  }
  return out
}

export function smpte(seconds: number, fps = 30): string {
  const total = Math.max(0, Math.round(seconds * fps))
  const f = total % fps
  const s = Math.floor(total / fps) % 60
  const m = Math.floor(total / fps / 60) % 60
  const h = Math.floor(total / fps / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(f)}`
}
