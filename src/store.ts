import { create } from 'zustand'
import { assignPoints } from './compiler/assign'
import { evaluateShow, showDuration } from './compiler/evaluate'
import { exportDshow, exportSkybrushCsv } from './compiler/export'
import { defaultShow, makeClip, makeTransition, parseShowPrompt } from './compiler/prompt'
import { analyzeSafety } from './compiler/safety'
import { sampleClip, volumeFromSettings } from './compiler/sample'
import type { Clip, SafetyReport, ShowSettings, Transition } from './compiler/types'
import { ClipKind, PresetName, TransitionStyle } from './compiler/types'

let rebuildToken = 0

type Selection =
  | { type: 'clip'; id: string }
  | { type: 'transition'; id: string }
  | null

type ShowState = {
  settings: ShowSettings
  clips: Clip[]
  transitions: Transition[]
  playhead: number
  playing: boolean
  compiling: boolean
  selection: Selection
  safety: SafetyReport | null
  label: string
  dropActive: boolean
  pos: Float32Array
  col: Float32Array
  duration: number
  setPlayhead: (t: number) => void
  togglePlay: () => void
  setPlaying: (v: boolean) => void
  patchSettings: (patch: Partial<ShowSettings>) => void
  select: (selection: Selection) => void
  updateClip: (id: string, patch: Partial<Clip>) => void
  updateTransition: (id: string, patch: Partial<Transition>) => void
  addPreset: (preset: PresetName | 'text') => void
  removeSelected: () => void
  applyPrompt: (text: string) => void
  importFiles: (files: File[]) => Promise<void>
  setDropActive: (v: boolean) => void
  useSuggestedDuration: (transitionId: string, duration: number) => void
  exportJson: () => void
  exportCsv: () => Promise<void>
  rebuild: () => Promise<void>
}

function syncDuration(clips: Clip[], transitions: Transition[]) {
  return showDuration(clips, transitions)
}

function syncBuffers(n: number, prevPos?: Float32Array, prevCol?: Float32Array) {
  const pos = prevPos && prevPos.length === n * 3 ? prevPos : new Float32Array(n * 3)
  const col = prevCol && prevCol.length === n * 3 ? prevCol : new Float32Array(n * 3)
  return { pos, col }
}

async function runRebuild(get: () => ShowState, set: (p: Partial<ShowState>) => void) {
  const token = ++rebuildToken
  set({ compiling: true })
  const { settings, clips, transitions } = get()
  const volume = volumeFromSettings(settings.width, settings.height, settings.depth)
  const nextClips: Clip[] = []
  for (const clip of clips) {
    if (clip.kind === ClipKind.Motion) {
      nextClips.push({ ...clip, points: null, colors: null })
      continue
    }
    const sampled = await sampleClip(clip, settings.droneCount, volume, settings.minSpacing)
    nextClips.push({ ...clip, points: sampled.points, colors: sampled.colors })
    if (token !== rebuildToken) return
  }

  const nextTransitions = transitions.map((tr, i) => {
    const from = [...nextClips].slice(0, i + 1).reverse().find((c) => c.kind !== ClipKind.Motion && c.points)
    const to = nextClips.slice(i + 1).find((c) => c.kind !== ClipKind.Motion && c.points)
    const assignment = from?.points && to?.points ? assignPoints(from.points, to.points) : []
    return { ...tr, assignment }
  })

  const draft = analyzeSafety(nextClips, nextTransitions, settings)
  const padded = nextTransitions.map((tr, i) => {
    const minT = draft.minTransitionDurations[i] ?? tr.duration
    return tr.duration + 0.05 < minT ? { ...tr, duration: Math.ceil(minT * 10) / 10 } : tr
  })
  const safety = analyzeSafety(nextClips, padded, settings)
  const { pos, col } = syncBuffers(settings.droneCount, get().pos, get().col)
  const firstHold = nextClips[0]?.hold ?? 0
  const playhead = get().playhead === 0 && nextClips.length > 1
    ? firstHold + (padded[0]?.duration ?? 0) + 0.4
    : get().playhead
  const ev = evaluateShow(nextClips, padded, settings, playhead, pos, col)
  if (token !== rebuildToken) return
  set({
    clips: nextClips,
    transitions: padded,
    safety,
    pos,
    col,
    playhead,
    label: ev.label,
    duration: syncDuration(nextClips, padded),
    compiling: false,
  })
}

const seed = defaultShow()
const seedBuf = syncBuffers(seed.settings.droneCount)

export const useShow = create<ShowState>((set, get) => ({
  settings: seed.settings,
  clips: seed.clips,
  transitions: seed.transitions,
  playhead: 0,
  playing: false,
  compiling: false,
  selection: seed.clips[1] ? { type: 'clip', id: seed.clips[1].id } : null,
  safety: null,
  label: 'Launch',
  dropActive: false,
  pos: seedBuf.pos,
  col: seedBuf.col,
  duration: syncDuration(seed.clips, seed.transitions),

  setPlayhead: (t) => {
    const { clips, transitions, settings, pos, col, duration } = get()
    const playhead = Math.max(0, Math.min(duration, t))
    const ev = evaluateShow(clips, transitions, settings, playhead, pos, col)
    set({ playhead, label: ev.label })
  },
  togglePlay: () => set({ playing: !get().playing }),
  setPlaying: (v) => set({ playing: v }),

  patchSettings: (patch) => {
    const settings = { ...get().settings, ...patch }
    const { pos, col } = syncBuffers(settings.droneCount, get().pos, get().col)
    set({ settings, pos, col })
    void get().rebuild()
  },

  select: (selection) => set({ selection }),

  updateClip: (id, patch) => {
    set({ clips: get().clips.map((c) => (c.id === id ? { ...c, ...patch } : c)) })
    if (patch.hold !== undefined || patch.color || patch.text || patch.kind || patch.preset) {
      if (patch.hold !== undefined && !patch.color && !patch.text && !patch.preset) {
        set({ duration: syncDuration(get().clips, get().transitions) })
        return
      }
      void get().rebuild()
    } else {
      set({ duration: syncDuration(get().clips, get().transitions) })
    }
  },

  updateTransition: (id, patch) => {
    set({
      transitions: get().transitions.map((t) => (t.id === id ? { ...t, ...patch } : t)),
    })
    const { clips, transitions, settings } = get()
    set({
      duration: syncDuration(clips, transitions),
      safety: analyzeSafety(clips, transitions, settings),
    })
  },

  addPreset: (preset) => {
    const { clips, transitions } = get()
    const landIdx = clips.findIndex((c) => c.preset === PresetName.Land)
    const insertAt = landIdx === -1 ? clips.length : landIdx
    const clip =
      preset === 'text'
        ? makeClip({ name: 'TEXT', kind: ClipKind.Text, text: 'TEXT', hold: 5, color: '#7ee8ff' })
        : makeClip({
            name: preset[0]!.toUpperCase() + preset.slice(1),
            kind: ClipKind.Preset,
            preset,
            hold: 5,
            color: preset === PresetName.Heart ? '#ff5a6a' : '#ffd4a8',
          })
    const nextClips = [...clips.slice(0, insertAt), clip, ...clips.slice(insertAt)]
    const nextTr = [...transitions.slice(0, insertAt), makeTransition(TransitionStyle.Morph, 5), ...transitions.slice(insertAt)]
    set({ clips: nextClips, transitions: nextTr.slice(0, Math.max(0, nextClips.length - 1)), selection: { type: 'clip', id: clip.id } })
    void get().rebuild()
  },

  removeSelected: () => {
    const { selection, clips, transitions } = get()
    if (!selection || clips.length <= 2) return
    if (selection.type === 'clip') {
      const idx = clips.findIndex((c) => c.id === selection.id)
      if (idx <= 0 || idx === clips.length - 1) return
      const nextClips = clips.filter((c) => c.id !== selection.id)
      const nextTr = transitions.filter((_, i) => i !== idx && i !== idx - 1)
      const patched = [...nextTr]
      if (nextClips.length > 1 && patched.length < nextClips.length - 1) {
        patched.splice(idx - 1, 0, makeTransition())
      }
      set({ clips: nextClips, transitions: patched.slice(0, nextClips.length - 1), selection: null })
      void get().rebuild()
    }
  },

  applyPrompt: (text) => {
    const parsed = parseShowPrompt(text, get().settings)
    const { pos, col } = syncBuffers(parsed.settings.droneCount)
    set({
      settings: parsed.settings,
      clips: parsed.clips,
      transitions: parsed.transitions,
      playhead: 0,
      pos,
      col,
      selection: parsed.clips[1] ? { type: 'clip', id: parsed.clips[1].id } : null,
    })
    void get().rebuild()
  },

  importFiles: async (files) => {
    const { clips, transitions } = get()
    const landIdx = clips.findIndex((c) => c.preset === PresetName.Land)
    const insertAt = landIdx === -1 ? clips.length : landIdx
    const added: Clip[] = []
    for (const file of files) {
      const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
      if (ext === 'svg') {
        const svgText = await file.text()
        added.push(makeClip({
          name: file.name.replace(/\.svg$/i, ''),
          kind: ClipKind.Svg,
          hold: 6,
          color: '#7ee8ff',
          asset: { type: 'svg', name: file.name, svgText },
        }))
      } else if (['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
        const bitmap = await createImageBitmap(file)
        added.push(makeClip({
          name: file.name.replace(/\.(png|jpe?g|webp)$/i, ''),
          kind: ClipKind.Image,
          hold: 6,
          color: '#f6f1e8',
          asset: { type: 'image', name: file.name, bitmap },
        }))
      } else if (['glb', 'gltf', 'obj', 'stl'].includes(ext)) {
        const buffer = await file.arrayBuffer()
        added.push(makeClip({
          name: file.name.replace(/\.(glb|gltf|obj|stl)$/i, ''),
          kind: ClipKind.Mesh,
          hold: 7,
          color: '#ffd4a8',
          asset: { type: 'mesh', name: file.name, buffer, ext },
        }))
      }
    }
    if (added.length === 0) return
    const nextClips = [...clips.slice(0, insertAt), ...added, ...clips.slice(insertAt)]
    const extra = added.map(() => makeTransition(TransitionStyle.Morph, 5))
    const nextTr = [...transitions.slice(0, insertAt), ...extra, ...transitions.slice(insertAt)]
    set({
      clips: nextClips,
      transitions: nextTr.slice(0, nextClips.length - 1),
      selection: { type: 'clip', id: added[0]!.id },
    })
    void get().rebuild()
  },

  setDropActive: (v) => set({ dropActive: v }),

  useSuggestedDuration: (transitionId, duration) => {
    get().updateTransition(transitionId, { duration })
  },

  exportJson: () => {
    const { clips, transitions, settings } = get()
    exportDshow(clips, transitions, settings)
  },
  exportCsv: async () => {
    const { clips, transitions, settings } = get()
    await exportSkybrushCsv(clips, transitions, settings)
  },

  rebuild: () => runRebuild(get, set),
}))

export function tickPlayback(dt: number) {
  const s = useShow.getState()
  if (!s.playing) return
  let next = s.playhead + dt
  if (next >= s.duration) {
    next = s.duration
    useShow.setState({ playing: false })
  }
  s.setPlayhead(next)
}

