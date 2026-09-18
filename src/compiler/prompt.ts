import { uid } from './math'
import type { Clip, ShowSettings, Transition } from './types'
import { ClipKind, MotionName, PresetName, TransitionStyle } from './types'

const COLORS: Record<string, string> = {
  red: '#ff3b3b',
  white: '#f6f1e8',
  gold: '#f0c14b',
  amber: '#ffb020',
  blue: '#4c8dff',
  cyan: '#7ee8ff',
  green: '#7cffb2',
  purple: '#c084fc',
}

export function defaultSettings(): ShowSettings {
  return {
    droneCount: 300,
    width: 150,
    height: 100,
    depth: 80,
    minSpacing: 2.5,
    maxVelocity: 8,
    maxAcceleration: 3,
    fps: 5,
  }
}

export function makeClip(partial: Partial<Clip> & Pick<Clip, 'name' | 'kind'>): Clip {
  return {
    id: uid('clip'),
    hold: 5,
    color: '#ffd4a8',
    points: null,
    colors: null,
    ...partial,
  }
}

export function makeTransition(style: Transition['style'] = TransitionStyle.Morph, duration = 5): Transition {
  return { id: uid('tr'), style, duration, assignment: null }
}

export function defaultShow(): { settings: ShowSettings; clips: Clip[]; transitions: Transition[] } {
  const settings = defaultSettings()
  const clips = [
    makeClip({ name: 'Launch', kind: ClipKind.Preset, preset: PresetName.Launch, hold: 3, color: '#d7dee8' }),
    makeClip({ name: 'Heart', kind: ClipKind.Preset, preset: PresetName.Heart, hold: 6, color: '#ff5a6a' }),
    makeClip({ name: 'Eagle', kind: ClipKind.Preset, preset: PresetName.Eagle, hold: 7, color: '#ffd4a8' }),
    makeClip({ name: 'DSHOW', kind: ClipKind.Text, text: 'DSHOW', hold: 6, color: '#7cffb2' }),
    makeClip({ name: 'Land', kind: ClipKind.Preset, preset: PresetName.Land, hold: 2, color: '#d7dee8' }),
  ]
  const transitions = clips.slice(0, -1).map((_, i) =>
    makeTransition(i === 1 ? TransitionStyle.Umap : TransitionStyle.Morph, i === 0 ? 14 : 8),
  )
  return { settings, clips, transitions }
}

function colorFromText(text: string): string | undefined {
  for (const [name, hex] of Object.entries(COLORS)) {
    if (new RegExp(`\\b${name}\\b`, 'i').test(text)) return hex
  }
}

function inferClip(phrase: string, color: string): Clip | null {
  const clean = phrase.replace(/\d+\s*(drones?|seconds?|s)\b/gi, '').replace(/hold(?: for)?/gi, '').trim()
  if (!clean || clean.length > 48) return null
  if (/^(\d+|and|with|total|show|red|white|gold|blue|cyan|green|purple|amber)$/i.test(clean)) return null
  if (/total show|and white|and red|seconds?$|^\d+$/i.test(clean)) return null
  if (/^(red|white|gold|blue|cyan|green|purple|amber)( and \w+)?$/i.test(clean)) return null
  if (/launch|takeoff/i.test(clean)) {
    return makeClip({ name: 'Launch', kind: ClipKind.Preset, preset: PresetName.Launch, color: '#d7dee8' })
  }
  if (/land|return home|rth/i.test(clean)) {
    return makeClip({ name: 'Land', kind: ClipKind.Preset, preset: PresetName.Land, color: '#d7dee8' })
  }
  if (/backflip|flip/i.test(clean)) {
    return makeClip({ name: 'Backflip', kind: ClipKind.Motion, motion: MotionName.Backflip, hold: 5, color })
  }
  if (/finale|burst|explode/i.test(clean)) {
    return makeClip({ name: 'Finale', kind: ClipKind.Preset, preset: PresetName.Burst, color })
  }
  if (/heart/i.test(clean)) return makeClip({ name: 'Heart', kind: ClipKind.Preset, preset: PresetName.Heart, color: '#ff5a6a' })
  if (/eagle|bird/i.test(clean)) return makeClip({ name: 'Eagle', kind: ClipKind.Preset, preset: PresetName.Eagle, color })
  if (/cobra/i.test(clean) && /logo|text/i.test(clean)) {
    return makeClip({ name: 'COBRA', kind: ClipKind.Text, text: 'COBRA', color })
  }
  if (/rider|motocross|motorcycle/i.test(clean)) {
    return makeClip({ name: 'Rider', kind: ClipKind.Preset, preset: PresetName.Rider, color })
  }
  if (/cobra/i.test(clean)) {
    return makeClip({ name: 'Cobra', kind: ClipKind.Preset, preset: PresetName.Cobra, color })
  }
  if (/star/i.test(clean)) return makeClip({ name: 'Star', kind: ClipKind.Preset, preset: PresetName.Star, color })
  if (/ring|circle/i.test(clean)) return makeClip({ name: 'Ring', kind: ClipKind.Preset, preset: PresetName.Ring, color })

  const quoted = clean.match(/["“]([^"”]+)["”]/)
  const caps = clean.match(/\b([A-Z][A-Z0-9]{1,16})\b/)
  const logo = clean.match(/([A-Za-z][A-Za-z0-9& ]{1,18}?)\s+logo/i)
  const word = quoted?.[1] ?? caps?.[1] ?? logo?.[1] ?? (clean.length <= 18 ? clean.replace(/transform|into|the|a|an/gi, '').trim() : '')
  const label = word.replace(/[^A-Za-z0-9 &.-]/g, '').trim()
  if (/second|total|show|white|drones|hold|transform/i.test(label)) return null
  if (label.length >= 2 && label.length <= 16) {
    return makeClip({ name: label.toUpperCase(), kind: ClipKind.Text, text: label.toUpperCase(), color })
  }
  return null
}

export function parseShowPrompt(text: string, current: ShowSettings): {
  settings: ShowSettings
  clips: Clip[]
  transitions: Transition[]
} {
  const settings = { ...current }
  const droneMatch = text.match(/(\d+)\s*drones?/i)
  if (droneMatch) settings.droneCount = Math.max(20, Math.min(2000, Number(droneMatch[1])))

  const totalMatch = text.match(/total(?: show)?\s+(\d+)/i)
  const holdMatch = text.match(/hold(?: for)?\s+(\d+)/i)
  const hold = holdMatch ? Number(holdMatch[1]) : 5
  const color = colorFromText(text) ?? '#ffd4a8'

  const parts = text
    .split(/\.\s+|transform into|, then | then | into /i)
    .map((s) => s.trim())
    .filter(Boolean)

  const clips: Clip[] = [
    makeClip({ name: 'Launch', kind: ClipKind.Preset, preset: PresetName.Launch, hold: 3, color: '#d7dee8' }),
  ]

  for (const part of parts) {
    const clip = inferClip(part, color)
    if (!clip) continue
    if (clip.name === 'Launch') continue
    clip.hold = clip.kind === ClipKind.Motion ? Math.max(4, hold) : hold
    if (clip.kind === ClipKind.Text || clip.kind === ClipKind.Preset) clip.color = clip.color === '#ffd4a8' ? color : clip.color
    const last = clips.at(-1)
    if (last && last.name === clip.name && last.kind === clip.kind) continue
    clips.push(clip)
  }

  if (!clips.some((c) => c.preset === PresetName.Land)) {
    clips.push(makeClip({ name: 'Land', kind: ClipKind.Preset, preset: PresetName.Land, hold: 2, color: '#d7dee8' }))
  }

  if (clips.length < 3) {
    return defaultShow()
  }

  const transCount = clips.length - 1
  let transition = 5
  if (totalMatch) {
    const total = Number(totalMatch[1])
    const holds = clips.reduce((s, c) => s + c.hold, 0)
    transition = Math.max(3, (total - holds) / Math.max(1, transCount))
    clips.forEach((c, i) => {
      if (i > 0 && i < clips.length - 1) c.hold = hold
    })
  }

  const transitions = clips.slice(0, -1).map((clip, i) => {
    const style =
      clip.kind === ClipKind.Motion ? TransitionStyle.Morph
      : /eagle|cobra|rider/i.test(clip.name) ? TransitionStyle.Umap
      : i === 0 ? TransitionStyle.Morph
      : TransitionStyle.Morph
    return makeTransition(style, Number(transition.toFixed(1)))
  })

  return { settings, clips, transitions }
}
