import { assignPoints } from './assign'
import { centroid, dist, lerpColor } from './math'
import { applyMotion, interpolateStyle } from './transitions'
import type { Clip, Color, ShowSettings, Transition, Vec3 } from './types'
import { ClipKind } from './types'

export type TimelineSpan =
  | { kind: 'clip'; clipIndex: number; start: number; end: number }
  | { kind: 'transition'; transitionIndex: number; start: number; end: number }

export function buildSpans(clips: Clip[], transitions: Transition[]): TimelineSpan[] {
  const spans: TimelineSpan[] = []
  let t = 0
  clips.forEach((clip, i) => {
    spans.push({ kind: 'clip', clipIndex: i, start: t, end: t + clip.hold })
    t += clip.hold
    const tr = transitions[i]
    if (tr && i < clips.length - 1) {
      spans.push({ kind: 'transition', transitionIndex: i, start: t, end: t + tr.duration })
      t += tr.duration
    }
  })
  return spans
}

export function showDuration(clips: Clip[], transitions: Transition[]): number {
  const spans = buildSpans(clips, transitions)
  return spans.at(-1)?.end ?? 0
}

export function spanAt(spans: TimelineSpan[], time: number): TimelineSpan | null {
  if (spans.length === 0) return null
  const t = Math.max(0, time)
  return spans.find((s) => t >= s.start && t < s.end) ?? spans.at(-1) ?? null
}

function lastStatic(clips: Clip[], index: number): Clip | null {
  for (let i = index; i >= 0; i--) {
    const clip = clips[i]
    if (clip && clip.kind !== ClipKind.Motion && clip.points) return clip
  }
  return clips.find((c) => c.points) ?? null
}

function nextStatic(clips: Clip[], index: number): Clip | null {
  for (let i = index; i < clips.length; i++) {
    const clip = clips[i]
    if (clip && clip.kind !== ClipKind.Motion && clip.points) return clip
  }
  return null
}

export function evaluateShow(
  clips: Clip[],
  transitions: Transition[],
  settings: ShowSettings,
  time: number,
  outPos: Float32Array,
  outCol: Float32Array,
): { label: string; span: TimelineSpan | null } {
  const n = settings.droneCount
  const spans = buildSpans(clips, transitions)
  const span = spanAt(spans, time)
  const empty = { label: '—', span }

  const write = (points: Vec3[], colors: Color[]) => {
    for (let i = 0; i < n; i++) {
      const p = points[i] ?? points[i % Math.max(1, points.length)] ?? { x: 0, y: 8, z: 0 }
      const c = colors[i] ?? colors[0] ?? { r: 1, g: 0.85, b: 0.7 }
      outPos[i * 3] = p.x
      outPos[i * 3 + 1] = p.y
      outPos[i * 3 + 2] = p.z
      outCol[i * 3] = c.r
      outCol[i * 3 + 1] = c.g
      outCol[i * 3 + 2] = c.b
    }
  }

  if (!span) return empty

  if (span.kind === 'clip') {
    const clip = clips[span.clipIndex]
    if (!clip) return empty
    if (clip.kind === ClipKind.Motion) {
      const base = lastStatic(clips, span.clipIndex - 1)
      if (!base?.points) return empty
      const u = (time - span.start) / Math.max(1e-4, clip.hold)
      write(applyMotion(base.points, clip.motion ?? 'backflip', u), base.colors ?? [])
      return { label: clip.name, span }
    }
    if (!clip.points) return empty
    write(clip.points, clip.colors ?? [])
    return { label: clip.name, span }
  }

  const tr = transitions[span.transitionIndex]
  const from = lastStatic(clips, span.transitionIndex)
  const to = nextStatic(clips, span.transitionIndex + 1)
  if (!tr || !from?.points || !to?.points) return empty

  const assignment = tr.assignment ?? assignPoints(from.points, to.points)
  const u = (time - span.start) / Math.max(1e-4, tr.duration)
  const fromC = centroid(from.points)
  const toC = centroid(to.points)
  let mean = 0
  for (let i = 0; i < from.points.length; i++) {
    const j = assignment[i] ?? i
    mean += dist(from.points[i]!, to.points[j] ?? to.points[0]!)
  }
  mean /= Math.max(1, from.points.length)

  for (let i = 0; i < n; i++) {
    const a = from.points[i] ?? from.points[0]!
    const j = assignment[i] ?? i
    const b = to.points[j] ?? to.points[i % to.points.length]!
    const p = interpolateStyle(a, b, u, tr.style, i, n, fromC, toC, mean)
    const ca = from.colors?.[i] ?? { r: 1, g: 0.85, b: 0.7 }
    const cb = to.colors?.[j] ?? to.colors?.[0] ?? ca
    const c = lerpColor(ca, cb, easeish(u, tr.style))
    outPos[i * 3] = p.x
    outPos[i * 3 + 1] = p.y
    outPos[i * 3 + 2] = p.z
    outCol[i * 3] = c.r
    outCol[i * 3 + 1] = c.g
    outCol[i * 3 + 2] = c.b
  }
  return { label: `${from.name} → ${to.name}`, span }
}

function easeish(t: number, style: string): number {
  if (style === 'direct') return t
  if (style === 'dissolve') return t < 0.5 ? 0 : (t - 0.5) * 2
  return t * t * (3 - 2 * t)
}
