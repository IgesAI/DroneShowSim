import type { AnimationClip, Formation, FormationPoint, Timeline, Vec3 } from '@lumina/schema'
import { applyColor, applyMotion, evaluateSegment, flightFloor, lerp3 } from './interpolation'

export type PlaybackFrame = {
  positions: Float32Array
  colors: Float32Array
  label: string
}

export function showDuration(timeline: Timeline): number {
  return timeline.duration
}

export function evaluateShow(
  formations: Formation[],
  timeline: Timeline,
  time: number,
  out?: PlaybackFrame,
): PlaybackFrame {
  const n = formations[0]?.points.length ?? 0
  const positions = out?.positions.length === n * 3 ? out.positions : new Float32Array(n * 3)
  const colors = out?.colors.length === n * 3 ? out.colors : new Float32Array(n * 3)
  const t = Math.max(0, time)

  const write = (pts: FormationPoint[], label: string, anim?: AnimationClip) => {
    let pose = pts.map((p) => p.position)
    let local = 0
    if (anim) {
      local = anim.loop
        ? ((t - anim.startTime) / Math.max(anim.duration, 1e-4)) % 1
        : (t - anim.startTime) / Math.max(anim.duration, 1e-4)
      if (local >= 0 && local <= 1) {
        const c: Vec3 = [0, 0, 0]
        for (const p of pose) {
          c[0] += p[0]
          c[1] += p[1]
          c[2] += p[2]
        }
        const inv = 1 / Math.max(pose.length, 1)
        c[0] *= inv
        c[1] *= inv
        c[2] *= inv
        pose = pose.map((p) => applyMotion(p, c, anim.motion, local, anim.amplitude))
      }
    }
    for (let i = 0; i < n; i++) {
      const p = pose[i] ?? pose[0] ?? [0, 0, 20]
      const raw = pts[i]?.color ?? [1, 0.85, 0.7]
      const col = anim ? applyColor(raw, anim.motion, local, anim.amplitude) : raw
      positions[i * 3] = p[0]
      positions[i * 3 + 1] = p[1]
      positions[i * 3 + 2] = Math.max(p[2], flightFloor(pts[i]?.position[2] ?? p[2]))
      colors[i * 3] = col[0]
      colors[i * 3 + 1] = col[1]
      colors[i * 3 + 2] = col[2]
    }
    return { positions, colors, label }
  }

  for (const cue of timeline.cues) {
    const end = cue.startTime + cue.holdDuration
    if (t >= cue.startTime && t < end) {
      const f = formations.find((x) => x.id === cue.formationId)
      const anim = (timeline.animations ?? []).find(
        (a) => a.formationId === cue.formationId && t >= a.startTime && t <= a.startTime + a.duration,
      )
      if (f) return write(f.points, anim ? `${f.name} · ${anim.name}` : f.name, anim)
    }
  }

  for (const tr of timeline.transitions) {
    const end = tr.startTime + tr.duration
    if (t >= tr.startTime && t <= end) {
      const from = formations.find((x) => x.id === tr.fromFormationId)
      const to = formations.find((x) => x.id === tr.toFormationId)
      if (!from || !to) continue
      const u = (t - tr.startTime) / Math.max(tr.duration, 1e-4)
      for (let i = 0; i < n; i++) {
        const a = from.points[i]
        const map = tr.assignment.find((x) => x.droneId === i) ?? tr.assignment[i]
        const b = to.points[map?.toPointId ?? i]
        if (!a || !b) continue
        const p = evaluateSegment(a.position, b.position, u, tr.type)
        const c = lerp3(a.color, b.color, u)
        positions[i * 3] = p[0]
        positions[i * 3 + 1] = p[1]
        positions[i * 3 + 2] = Math.max(p[2], flightFloor(a.position[2], b.position[2]))
        colors[i * 3] = c[0]
        colors[i * 3 + 1] = c[1]
        colors[i * 3 + 2] = c[2]
      }
      return { positions, colors, label: `${from.name} → ${to.name}` }
    }
  }

  const last = formations.at(-1)
  return last ? write(last.points, last.name) : { positions, colors, label: '—' }
}
