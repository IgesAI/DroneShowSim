import { dist } from './math'
import type { Clip, SafetyIssue, SafetyReport, ShowSettings, Transition, Vec3 } from './types'
import { ClipKind } from './types'

function peakForDistance(distance: number, duration: number): { vel: number; acc: number } {
  const T = Math.max(duration, 1e-3)
  return {
    vel: (1.5 * distance) / T,
    acc: (6 * distance) / (T * T),
  }
}

function minDurationForDistance(distance: number, settings: ShowSettings): number {
  const tv = (1.5 * distance) / Math.max(settings.maxVelocity, 0.1)
  const ta = Math.sqrt((6 * distance) / Math.max(settings.maxAcceleration, 0.1))
  return Math.max(tv, ta, 0.4)
}

function lastStatic(clips: Clip[], index: number): Clip | undefined {
  for (let i = index; i >= 0; i--) {
    const clip = clips[i]
    if (clip && clip.kind !== ClipKind.Motion && clip.points) return clip
  }
}

function nextStatic(clips: Clip[], index: number): Clip | undefined {
  for (let i = index; i < clips.length; i++) {
    const clip = clips[i]
    if (clip && clip.kind !== ClipKind.Motion && clip.points) return clip
  }
}

function minPairDistance(points: Vec3[]): number {
  let min = Infinity
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) {
      min = Math.min(min, dist(points[i]!, points[j]!))
    }
  }
  return min
}

export function analyzeSafety(clips: Clip[], transitions: Transition[], settings: ShowSettings): SafetyReport {
  const issues: SafetyIssue[] = []
  const minTransitionDurations: number[] = []
  let peakVelocity = 0
  let peakAcceleration = 0
  let minSeparation = Infinity

  const neededArea = settings.droneCount * settings.minSpacing ** 2 * 0.86
  const haveArea = settings.width * settings.height
  if (neededArea > haveArea * 1.15) {
    issues.push({
      level: 'warn',
      message: `${settings.droneCount} drones at ${settings.minSpacing}m spacing need more area than ${settings.width}×${settings.height}m.`,
    })
  }

  for (const clip of clips) {
    if (!clip.points || clip.kind === ClipKind.Motion) continue
    const sep = minPairDistance(clip.points)
    minSeparation = Math.min(minSeparation, sep)
    if (sep < settings.minSpacing * 0.92) {
      issues.push({
        level: 'warn',
        message: `${clip.name} has ${sep.toFixed(2)}m minimum spacing (limit ${settings.minSpacing}m).`,
        clipId: clip.id,
      })
    }
  }

  transitions.forEach((tr, i) => {
    const from = lastStatic(clips, i)
    const to = nextStatic(clips, i + 1)
    if (!from?.points || !to?.points || !tr.assignment) {
      minTransitionDurations.push(tr.duration)
      return
    }
    let worst = 0
    for (let d = 0; d < from.points.length; d++) {
      const j = tr.assignment[d] ?? d
      const distance = dist(from.points[d]!, to.points[j] ?? to.points[0]!)
      worst = Math.max(worst, distance)
      const peak = peakForDistance(distance, tr.duration)
      peakVelocity = Math.max(peakVelocity, peak.vel)
      peakAcceleration = Math.max(peakAcceleration, peak.acc)
    }
    const minT = minDurationForDistance(worst, settings)
    minTransitionDurations.push(minT)
    if (tr.duration + 1e-3 < minT) {
      issues.push({
        level: 'error',
        message: `${tr.duration.toFixed(1)}s ${from.name} → ${to.name} is impossible. Minimum safe duration: ${minT.toFixed(1)}s.`,
        transitionId: tr.id,
        suggestedDuration: Math.ceil(minT * 10) / 10,
      })
    }
  })

  if (peakVelocity > settings.maxVelocity) {
    issues.push({
      level: 'error',
      message: `Peak velocity ${peakVelocity.toFixed(1)} m/s exceeds ${settings.maxVelocity} m/s.`,
    })
  }
  if (peakAcceleration > settings.maxAcceleration) {
    issues.push({
      level: 'error',
      message: `Peak acceleration ${peakAcceleration.toFixed(1)} m/s² exceeds ${settings.maxAcceleration} m/s².`,
    })
  }

  return {
    ok: issues.every((i) => i.level !== 'error'),
    minTransitionDurations,
    issues,
    peakVelocity,
    peakAcceleration,
    minSeparation: Number.isFinite(minSeparation) ? minSeparation : 0,
  }
}
