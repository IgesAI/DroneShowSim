import { dist2 } from './math'
import type { Vec3 } from './types'

/** Greedy nearest-unique matching plus 2-opt swaps. Fast enough for ~2000 drones. */
export function assignPoints(from: Vec3[], to: Vec3[]): number[] {
  const n = Math.min(from.length, to.length)
  if (n === 0) return []

  const pairs: { i: number; j: number; d: number }[] = new Array(n * n)
  let k = 0
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      pairs[k++] = { i, j, d: dist2(from[i]!, to[j]!) }
    }
  }
  pairs.sort((a, b) => a.d - b.d)

  const usedI = new Uint8Array(n)
  const usedJ = new Uint8Array(n)
  const assignment = new Array<number>(from.length).fill(0)
  let left = n
  for (const p of pairs) {
    if (usedI[p.i] || usedJ[p.j]) continue
    assignment[p.i] = p.j
    usedI[p.i] = 1
    usedJ[p.j] = 1
    if (--left === 0) break
  }

  const rounds = n > 800 ? 3 : n > 400 ? 5 : 8
  for (let iter = 0; iter < rounds; iter++) {
    let improved = false
    for (let i = 0; i < n; i++) {
      const j = assignment[i]!
      for (let a = i + 1; a < n; a++) {
        const b = assignment[a]!
        const current = dist2(from[i]!, to[j]!) + dist2(from[a]!, to[b]!)
        const swapped = dist2(from[i]!, to[b]!) + dist2(from[a]!, to[j]!)
        if (swapped + 1e-9 < current) {
          assignment[i] = b
          assignment[a] = j
          improved = true
        }
      }
    }
    if (!improved) break
  }

  if (from.length > n) {
    for (let i = n; i < from.length; i++) assignment[i] = i % to.length
  }
  return assignment
}

export function assignmentCost(from: Vec3[], to: Vec3[], assignment: number[]): number {
  let sum = 0
  for (let i = 0; i < from.length; i++) {
    const j = assignment[i] ?? i
    const b = to[j] ?? to[i % to.length]
    if (!b) continue
    sum += Math.sqrt(dist2(from[i]!, b))
  }
  return sum
}
