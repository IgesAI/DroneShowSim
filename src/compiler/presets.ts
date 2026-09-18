import { farthestPointSample, fitToVolume, vec } from './math'
import type { Vec3, Volume } from './types'
import { PresetName } from './types'

function grid(n: number, spacing: number, y: number): Vec3[] {
  const cols = Math.ceil(Math.sqrt(n))
  const rows = Math.ceil(n / cols)
  const pts: Vec3[] = []
  for (let i = 0; i < n; i++) {
    const c = i % cols
    const r = Math.floor(i / cols)
    const x = (c - (cols - 1) / 2) * spacing
    const z = (r - (rows - 1) / 2) * spacing
    pts.push(vec(x, y, z))
  }
  return pts
}

function heartCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  for (let i = 0; i < count; i++) {
    const t = (i / count) * Math.PI * 2
    const x = 16 * Math.sin(t) ** 3
    const y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)
    pts.push(vec(x, y, 0))
  }
  for (let i = 0; i < count * 2; i++) {
    const t = Math.random() * Math.PI * 2
    const u = Math.random() ** 0.65
    const x = 16 * Math.sin(t) ** 3 * u
    const y = (13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) * u
    pts.push(vec(x, y, (Math.random() - 0.5) * 0.3))
  }
  return pts
}

function starCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  const spikes = 5
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2
    const spike = Math.floor(((a + Math.PI / 2) / (Math.PI * 2)) * spikes * 2)
    const r = spike % 2 === 0 ? 1 : 0.42
    pts.push(vec(Math.cos(a) * r, Math.sin(a) * r, 0))
  }
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2
    const r = Math.random() ** 0.7 * 0.85
    pts.push(vec(Math.cos(a) * r, Math.sin(a) * r, 0))
  }
  return pts
}

function ringCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2
    pts.push(vec(Math.cos(a), Math.sin(a), 0))
    if (i % 3 === 0) pts.push(vec(Math.cos(a) * 0.72, Math.sin(a) * 0.72, 0))
  }
  return pts
}

function burstCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  for (let i = 0; i < count * 3; i++) {
    const u = Math.random()
    const v = Math.random()
    const theta = 2 * Math.PI * u
    const phi = Math.acos(2 * v - 1)
    const r = 0.55 + Math.random() * 0.45
    pts.push(vec(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(theta),
    ))
  }
  return pts
}

function eagleCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  const pushEllipsoid = (cx: number, cy: number, cz: number, rx: number, ry: number, rz: number, n: number) => {
    for (let i = 0; i < n; i++) {
      const u = Math.random()
      const v = Math.random()
      const theta = 2 * Math.PI * u
      const phi = Math.acos(2 * v - 1)
      pts.push(vec(
        cx + rx * Math.sin(phi) * Math.cos(theta),
        cy + ry * Math.cos(phi),
        cz + rz * Math.sin(phi) * Math.sin(theta),
      ))
    }
  }
  pushEllipsoid(0, 0, 0, 0.55, 0.28, 0.22, count)
  pushEllipsoid(0.62, 0.18, 0, 0.22, 0.18, 0.16, count * 0.35)
  pushEllipsoid(0.82, 0.12, 0, 0.1, 0.06, 0.05, count * 0.08)
  for (let i = 0; i < count; i++) {
    const t = i / count
    const span = (t - 0.5) * 2.6
    const taper = 1 - Math.abs(t - 0.5) * 1.2
    pts.push(vec(span * 0.15, 0.05 + Math.sin(t * Math.PI) * 0.08, span * 0.55 * taper))
    pts.push(vec(span * 0.08, 0.02, -span * 0.55 * taper))
  }
  for (let i = 0; i < count * 0.25; i++) {
    const t = i / (count * 0.25)
    pts.push(vec(-0.7 - t * 0.35, (t - 0.5) * 0.35, (Math.random() - 0.5) * 0.12))
  }
  return pts
}

function riderCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  const stroke = (ax: number, ay: number, bx: number, by: number, n: number) => {
    for (let i = 0; i < n; i++) {
      const t = i / Math.max(1, n - 1)
      pts.push(vec(ax + (bx - ax) * t, ay + (by - ay) * t, 0))
    }
  }
  const circle = (cx: number, cy: number, r: number, n: number) => {
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2
      pts.push(vec(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 0))
    }
  }
  circle(-0.7, -0.45, 0.28, Math.ceil(count * 0.18))
  circle(0.7, -0.45, 0.28, Math.ceil(count * 0.18))
  stroke(-0.7, -0.45, 0.7, -0.45, Math.ceil(count * 0.12))
  stroke(-0.15, -0.45, 0.15, 0.05, Math.ceil(count * 0.08))
  stroke(-0.55, -0.2, 0.55, -0.05, Math.ceil(count * 0.1))
  stroke(0.1, 0.05, 0.05, 0.55, Math.ceil(count * 0.1))
  circle(0.08, 0.78, 0.14, Math.ceil(count * 0.1))
  stroke(0.05, 0.5, -0.35, 0.15, Math.ceil(count * 0.07))
  stroke(0.05, 0.5, 0.42, 0.22, Math.ceil(count * 0.07))
  return pts
}

function cobraCandidates(count: number): Vec3[] {
  const pts: Vec3[] = []
  for (let i = 0; i < count; i++) {
    const t = i / count
    const x = (t - 0.5) * 2.2
    const hood = Math.exp(-((t - 0.72) ** 2) * 18) * 0.85
    const body = Math.sin(t * Math.PI) * 0.18
    pts.push(vec(x, body + hood * 0.15, (Math.random() - 0.5) * 0.05))
    if (t > 0.55 && t < 0.9) {
      pts.push(vec(x + 0.02, 0.15 + hood, 0))
      pts.push(vec(x - 0.02, 0.15 + hood * 0.4, 0))
      pts.push(vec(x, 0.55 * hood + 0.2, (t - 0.72) * 0.8))
      pts.push(vec(x, 0.55 * hood + 0.2, -(t - 0.72) * 0.8))
    }
  }
  return pts
}

export function samplePreset(name: PresetName, n: number, volume: Volume, minSpacing = 2.5): Vec3[] {
  if (name === PresetName.Launch || name === PresetName.Land) {
    return grid(n, Math.max(minSpacing * 1.15, 2.2), name === PresetName.Land ? 0.6 : 0.8)
  }
  const raw =
    name === PresetName.Heart ? heartCandidates(n * 4)
    : name === PresetName.Star ? starCandidates(n * 4)
    : name === PresetName.Ring ? ringCandidates(n * 3)
    : name === PresetName.Eagle ? eagleCandidates(n * 4)
    : name === PresetName.Rider ? riderCandidates(n * 3)
    : name === PresetName.Cobra ? cobraCandidates(n * 4)
    : burstCandidates(n * 4)
  const picked = farthestPointSample(raw, n)
  const flat = name !== PresetName.Eagle && name !== PresetName.Burst
  return fitToVolume(picked, volume, flat)
}
