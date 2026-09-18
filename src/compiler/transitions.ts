import { add, bezier, centroid, easeInOutCubic, lerp, normalize, rotateY, scale, smoothstep, sub, vec } from './math'
import type { TransitionStyle, Vec3 } from './types'

function autoStyle(a: Vec3, b: Vec3, meanDist: number): TransitionStyle {
  const d = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)
  if (d > meanDist * 1.6) return 'explode'
  if (Math.abs(a.y - b.y) > meanDist) return 'dissolve'
  return 'morph'
}

export function interpolateStyle(
  a: Vec3,
  b: Vec3,
  t: number,
  style: TransitionStyle,
  index: number,
  count: number,
  fromCentroid: Vec3,
  toCentroid: Vec3,
  meanDist: number,
): Vec3 {
  const resolved = style === 'auto' ? autoStyle(a, b, meanDist) : style
  const e = easeInOutCubic(t)
  const pivot = lerp(fromCentroid, toCentroid, e)

  switch (resolved) {
    case 'direct':
      return lerp(a, b, t)
    case 'morph':
      return lerp(a, b, e)
    case 'explode': {
      const away = normalize(sub(a, fromCentroid))
      const mid = add(lerp(a, b, 0.5), scale(away, meanDist * 0.55 + 8))
      return bezier(a, mid, b, e)
    }
    case 'collapse': {
      const mid = lerp(fromCentroid, toCentroid, 0.5)
      return bezier(a, mid, b, e)
    }
    case 'orbit': {
      const spun = rotateY(a, e * Math.PI, pivot)
      return lerp(spun, b, e)
    }
    case 'wave': {
      const delay = (index / Math.max(1, count - 1)) * 0.45
      const local = smoothstep((t - delay) / (1 - delay))
      return lerp(a, b, easeInOutCubic(local))
    }
    case 'dissolve': {
      const down = vec(a.x, Math.min(a.y, 4) - 6, a.z)
      const up = vec(b.x, Math.min(b.y, 4) - 6, b.z)
      if (t < 0.5) return lerp(a, down, easeInOutCubic(t * 2))
      return lerp(up, b, easeInOutCubic((t - 0.5) * 2))
    }
    case 'umap': {
      const flatA = { x: a.x, y: a.y, z: fromCentroid.z }
      const flatB = { x: b.x, y: b.y, z: toCentroid.z }
      if (t < 0.34) return lerp(a, flatA, easeInOutCubic(t / 0.34))
      if (t < 0.66) {
        const u = (t - 0.34) / 0.32
        const p = lerp(flatA, flatB, easeInOutCubic(u))
        return rotateY(p, u * Math.PI * 0.7, pivot)
      }
      return lerp(flatB, b, easeInOutCubic((t - 0.66) / 0.34))
    }
    case 'fluid': {
      const p = lerp(a, b, e)
      const dir = sub(b, a)
      p.x += Math.sin(t * Math.PI * 2 + index * 0.17) * 4
      p.y += Math.sin(t * Math.PI + dir.x * 0.02) * 3
      return p
    }
    case 'vortex': {
      const spun = rotateY(lerp(a, b, e * 0.35), e * Math.PI * 2, pivot)
      return lerp(spun, b, e)
    }
    default:
      return lerp(a, b, e)
  }
}

export function applyMotion(points: Vec3[], motion: string, t: number): Vec3[] {
  const c = centroid(points)
  const e = easeInOutCubic(t)
  if (motion === 'backflip') {
    return points.map((p) => {
      const rx = e * Math.PI * 2
      const y = p.y - c.y
      const z = p.z - c.z
      return {
        x: p.x,
        y: c.y + y * Math.cos(rx) - z * Math.sin(rx),
        z: c.z + y * Math.sin(rx) + z * Math.cos(rx),
      }
    })
  }
  if (motion === 'orbit') {
    return points.map((p) => rotateY(p, e * Math.PI * 2, c))
  }
  return points.map((p, i) => ({
    x: p.x,
    y: p.y + Math.sin(e * Math.PI * 2 + i * 0.2) * 4,
    z: p.z,
  }))
}
