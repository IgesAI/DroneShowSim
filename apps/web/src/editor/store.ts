'use client'

import {
  CLOCK_DOMAIN,
  COLOR_SPACE,
  COMPILER_VERSION,
  COORDINATE_SYSTEM,
  SCHEMA_VERSION,
  defaultAudience,
  defaultDroneProfile,
  defaultSafetyProfile,
  type AnimationClip,
  type AnimationMotion,
  type ShowProject,
  type Transition,
  type TransitionType,
  type Violation,
} from '@lumina/schema'
import { create } from 'zustand'
import { compileDemo, compileShow, generateFormation } from './api'
import { isMesh, type ImportKind } from './assets'

export function emptyShow(count = 80): ShowProject {
  return {
    version: SCHEMA_VERSION,
    schemaVersion: SCHEMA_VERSION,
    compilerVersion: COMPILER_VERSION,
    id: 'show_local',
    name: 'Untitled',
    coordinateSystem: COORDINATE_SYSTEM,
    colorSpace: COLOR_SPACE,
    clockDomain: CLOCK_DOMAIN,
    showState: 'UNCOMPILED',
    droneProfile: defaultDroneProfile(count),
    venue: {
      latitude: 0,
      longitude: 0,
      altitude: 0,
      altitudeDatum: 'local-z',
      groundZ: 0,
      showHeadingRad: 0,
      audience: defaultAudience(),
    },
    assets: [],
    formations: [],
    timeline: { duration: 0, cues: [], transitions: [], animations: [] },
    safetyProfile: defaultSafetyProfile(),
    slots: [],
    compilerNotes: [],
    proximityViolations: [],
  }
}

const MOTION_META: Record<AnimationMotion, { name: string; kind: 'rigid' | 'procedural' }> = {
  backflip: { name: 'Backflip', kind: 'rigid' },
  orbit: { name: 'Orbit', kind: 'rigid' },
  advance: { name: 'Advance', kind: 'rigid' },
  yaw: { name: 'Yaw', kind: 'rigid' },
  wave: { name: 'Wave', kind: 'procedural' },
  flap: { name: 'Flap', kind: 'procedural' },
  pulse: { name: 'Pulse', kind: 'procedural' },
  chroma: { name: 'Chroma', kind: 'procedural' },
}

function rebuildTransitions(project: ShowProject, cues: ShowProject['timeline']['cues']): Transition[] {
  return cues.slice(0, -1).map((cue, i) => {
    const to = cues[i + 1]
    const existing = project.timeline.transitions.find(
      (t) => t.fromFormationId === cue.formationId && t.toFormationId === to.formationId,
    )
    return {
      id: existing?.id ?? `tr_${cue.formationId}_${to.formationId}`,
      fromFormationId: cue.formationId,
      toFormationId: to.formationId,
      startTime: 0,
      duration: existing?.duration ?? 6,
      durationMode: existing?.durationMode ?? 'auto',
      type: existing?.type ?? 'morph',
      assignment: [],
      trajectorySetId: '',
    }
  })
}

type EditorState = {
  project: ShowProject | null
  playhead: number
  playing: boolean
  loop: boolean
  compiling: boolean
  error: string | null
  selectedId: string | null
  violations: Violation[]
  showCapsules: boolean
  audienceView: boolean
  loadDemo: (count?: number) => Promise<void>
  recompile: () => Promise<void>
  setPlayhead: (t: number) => void
  togglePlay: () => void
  play: () => void
  pause: () => void
  rewind: () => void
  skipCue: (dir: -1 | 1) => void
  stepFrame: (dir: -1 | 1) => void
  setLoop: (v: boolean) => void
  setPlaying: (v: boolean) => void
  patchCount: (n: number) => Promise<void>
  importAsset: (name: string, content: string, kind: ImportKind) => Promise<void>
  importSvg: (name: string, content: string) => Promise<void>
  addAnimation: (formationId: string, motion: AnimationMotion) => Promise<void>
  select: (id: string | null) => void
  removeSelected: () => Promise<void>
  removeAsset: (assetId: string) => Promise<void>
  reorderCue: (formationId: string, toIndex: number) => Promise<void>
  patchHold: (formationId: string, hold: number, compile?: boolean) => Promise<void>
  patchAnimation: (id: string, patch: Partial<Pick<AnimationClip, 'cueOffset' | 'duration' | 'amplitude' | 'loop' | 'name'>>, compile?: boolean) => Promise<void>
  patchTransition: (id: string, patch: Partial<Pick<Transition, 'duration' | 'durationMode' | 'type'>>, compile?: boolean) => Promise<void>
  renameFormation: (id: string, name: string) => void
  patchPitch: (m: number, compile?: boolean) => Promise<void>
  setShowCapsules: (v: boolean) => void
  setAudienceView: (v: boolean) => void
  seekViolation: (v: Violation) => void
}

let compileGen = 0

export const useEditor = create<EditorState>((set, get) => ({
  project: null,
  playhead: 0,
  playing: false,
  loop: false,
  compiling: false,
  error: null,
  selectedId: null,
  violations: [],
  showCapsules: false,
  audienceView: false,

  loadDemo: async (count = 80) => {
    const gen = ++compileGen
    set({ compiling: true, error: null, playing: false })
    try {
      const { project, violations } = await compileDemo(count, 1)
      if (gen !== compileGen) return
      set({ project, violations: violations.length ? violations : project.proximityViolations ?? [], playhead: project.timeline.cues[0]?.startTime ?? 0, compiling: false })
    } catch (err) {
      if (gen !== compileGen) return
      set({ compiling: false, error: err instanceof Error ? err.message : 'Compile failed' })
    }
  },

  recompile: async () => {
    const { project } = get()
    if (!project) return
    const gen = ++compileGen
    set({ compiling: true, error: null })
    try {
      const { project: next, violations } = await compileShow(project)
      if (gen !== compileGen) return
      const playhead = Math.min(get().playhead, next.timeline.duration)
      set({ project: next, violations, compiling: false, playhead, error: null })
    } catch (err) {
      if (gen !== compileGen) return
      set({ compiling: false, error: err instanceof Error ? err.message : 'Compile failed' })
    }
  },

  setPlayhead: (t) => {
    const duration = get().project?.timeline.duration ?? 0
    set({ playhead: Math.max(0, Math.min(duration, t)) })
  },
  togglePlay: () => set({ playing: !get().playing }),
  play: () => set({ playing: true }),
  pause: () => set({ playing: false }),
  rewind: () => set({ playing: false, playhead: 0 }),
  setLoop: (v) => set({ loop: v }),
  setPlaying: (v) => set({ playing: v }),
  select: (id) => set({ selectedId: id }),

  skipCue: (dir) => {
    const { project, playhead, setPlayhead, pause } = get()
    if (!project) return
    const cues = project.timeline.cues
    if (dir < 0) {
      const prev = [...cues].reverse().find((c) => c.startTime < playhead - 0.05)
      pause()
      setPlayhead(prev?.startTime ?? 0)
      return
    }
    const next = cues.find((c) => c.startTime > playhead + 0.05)
    pause()
    setPlayhead(next?.startTime ?? project.timeline.duration)
  },

  stepFrame: (dir) => {
    get().pause()
    get().setPlayhead(get().playhead + dir / 30)
  },

  patchCount: async (n) => {
    const { project } = get()
    if (!project) return
    const next = {
      ...project,
      droneProfile: { ...project.droneProfile, count: n },
      formations: project.formations.map((f) => ({ ...f, points: [] })),
    }
    set({ project: next, compiling: true, error: null, playing: false })
    try {
      const { project: compiled, violations } = await compileShow(next)
      set({ project: compiled, violations, compiling: false, playhead: 0 })
    } catch (err) {
      set({ compiling: false, error: err instanceof Error ? err.message : 'Compile failed' })
    }
  },

  importAsset: async (name, content, kind) => {
    const project = get().project ?? emptyShow()
    if (!get().project) set({ project })
    set({ compiling: true, error: null })
    const id = `asset_${Math.random().toString(36).slice(2, 8)}`
    const mesh = isMesh(kind)
    try {
      const generated = await generateFormation({
        assetId: id,
        name,
        content,
        kind,
        mode: mesh ? 'surface' : 'feature',
        depthMeters: mesh ? 48 : 0,
        droneCount: project.droneProfile.count,
        widthMeters: mesh ? 48 : 90,
        heightMeters: mesh ? 48 : 42,
        seed: 1,
      })
      const formation = generated.formation
      const formations = [...project.formations, formation]
      const cue = { id: `cue_${id}`, formationId: formation.id, startTime: 0, holdDuration: 5, phase: 'show' as const }
      const cues = [...project.timeline.cues]
      const land = cues.findIndex((c) => c.phase === 'landing')
      if (land >= 0) cues.splice(land, 0, cue)
      else cues.push(cue)
      const next: ShowProject = {
        ...project,
        name: project.assets.length === 0 ? name : project.name,
        assets: [...project.assets, { id, name, kind, content }],
        formations,
        timeline: {
          ...project.timeline,
          cues,
          transitions: rebuildTransitions({ ...project, formations }, cues),
          animations: project.timeline.animations ?? [],
        },
      }
      set({ project: next, selectedId: formation.id })
      await get().recompile()
    } catch (err) {
      set({ compiling: false, error: err instanceof Error ? err.message : 'Import failed' })
    }
  },

  importSvg: async (name, content) => get().importAsset(name, content, 'svg'),

  addAnimation: async (formationId, motion) => {
    const { project } = get()
    if (!project) return
    const meta = MOTION_META[motion]
    const clip: AnimationClip = {
      id: `anim_${Math.random().toString(36).slice(2, 8)}`,
      name: meta.name,
      kind: meta.kind,
      formationId,
      cueOffset: 0.8,
      startTime: 0,
      duration: 4,
      loop: false,
      motion,
      amplitude: 1,
    }
    set({
      project: {
        ...project,
        timeline: {
          ...project.timeline,
          animations: [...(project.timeline.animations ?? []), clip],
        },
      },
      selectedId: clip.id,
      playing: false,
    })
    await get().recompile()
  },

  removeAsset: async (assetId) => {
    const { project } = get()
    if (!project) return
    const doomed = new Set(project.formations.filter((f) => f.sourceAssetId === assetId).map((f) => f.id))
    if (doomed.size >= project.formations.length) {
      set({ error: 'Keep at least one formation' })
      return
    }
    const formations = project.formations.filter((f) => !doomed.has(f.id))
    const cues = project.timeline.cues.filter((c) => !doomed.has(c.formationId))
    const next: ShowProject = {
      ...project,
      assets: project.assets.filter((a) => a.id !== assetId),
      formations,
      timeline: {
        ...project.timeline,
        cues,
        transitions: rebuildTransitions({ ...project, formations }, cues),
        animations: (project.timeline.animations ?? []).filter((a) => !doomed.has(a.formationId)),
      },
    }
    set({ project: next, selectedId: formations[0]?.id ?? null, playing: false })
    await get().recompile()
  },

  removeSelected: async () => {
    const { project, selectedId } = get()
    if (!project || !selectedId) return
    if (selectedId === 'frm_launch' || selectedId === 'cue_launch' || selectedId === 'cue_land') {
      set({ error: 'Launch/landing grid is owned by the compiler' })
      return
    }
    const asset = project.assets.find((a) => a.id === selectedId)
    if (asset) {
      await get().removeAsset(asset.id)
      return
    }
    const animation = (project.timeline.animations ?? []).find((a) => a.id === selectedId)
    if (animation) {
      set({
        project: {
          ...project,
          timeline: {
            ...project.timeline,
            animations: project.timeline.animations.filter((a) => a.id !== selectedId),
          },
        },
        selectedId: animation.formationId,
      })
      await get().recompile()
      return
    }
    if (project.timeline.transitions.some((tr) => tr.id === selectedId)) {
      set({ error: 'Reorder or delete a cue to change transitions' })
      return
    }
    const formation = project.formations.find((f) => f.id === selectedId)
    if (!formation) return
    if (project.formations.length <= 1) {
      set({ error: 'Keep at least one formation' })
      return
    }
    const formations = project.formations.filter((f) => f.id !== formation.id)
    const cues = project.timeline.cues.filter((c) => c.formationId !== formation.id)
    const assetStillUsed = formations.some((f) => f.sourceAssetId === formation.sourceAssetId)
    const next: ShowProject = {
      ...project,
      assets: assetStillUsed ? project.assets : project.assets.filter((a) => a.id !== formation.sourceAssetId),
      formations,
      timeline: {
        ...project.timeline,
        cues,
        transitions: rebuildTransitions({ ...project, formations }, cues),
        animations: (project.timeline.animations ?? []).filter((a) => a.formationId !== formation.id),
      },
    }
    set({ project: next, selectedId: formations[0]?.id ?? null, playing: false })
    await get().recompile()
  },

  reorderCue: async (formationId, toIndex) => {
    const { project } = get()
    if (!project) return
    if (formationId === 'frm_launch') return
    const cues = [...project.timeline.cues]
    const from = cues.findIndex((c) => c.formationId === formationId && c.phase === 'show')
    const lo = cues[0]?.phase === 'takeoff' ? 1 : 0
    const hi = cues.at(-1)?.phase === 'landing' ? cues.length - 2 : cues.length - 1
    toIndex = Math.max(lo, Math.min(hi, toIndex))
    if (from < 0 || from === toIndex) return
    const [moved] = cues.splice(from, 1)
    cues.splice(toIndex, 0, moved)
    set({
      project: {
        ...project,
        timeline: {
          ...project.timeline,
          cues,
          transitions: rebuildTransitions(project, cues),
        },
      },
      playing: false,
    })
    await get().recompile()
  },

  patchHold: async (formationId, hold, compile = true) => {
    const { project } = get()
    if (!project) return
    const nextHold = Math.max(1, Math.min(40, hold))
    set({
      project: {
        ...project,
        timeline: {
          ...project.timeline,
          cues: project.timeline.cues.map((c) => (c.formationId === formationId ? { ...c, holdDuration: nextHold } : c)),
        },
      },
    })
    if (compile) await get().recompile()
  },

  patchAnimation: async (id, patch, compile = true) => {
    const { project } = get()
    if (!project) return
    set({
      project: {
        ...project,
        timeline: {
          ...project.timeline,
          animations: (project.timeline.animations ?? []).map((a) => (a.id === id ? { ...a, ...patch } : a)),
        },
      },
    })
    if (compile) await get().recompile()
  },

  patchTransition: async (id, patch, compile = true) => {
    const { project } = get()
    if (!project) return
    set({
      project: {
        ...project,
        timeline: {
          ...project.timeline,
          transitions: project.timeline.transitions.map((t) =>
            t.id === id
              ? {
                  ...t,
                  ...patch,
                  assignment:
                    (patch.type !== undefined && patch.type !== t.type) || patch.duration !== undefined ? [] : t.assignment,
                  durationMode: patch.duration !== undefined ? 'manual' : (patch.durationMode ?? t.durationMode),
                }
              : t,
          ),
        },
      },
    })
    if (compile) await get().recompile()
  },

  patchPitch: async (m, compile = true) => {
    const { project } = get()
    if (!project) return
    const pitch = Math.max(2, Math.min(12, m))
    set({
      project: {
        ...project,
        droneProfile: { ...project.droneProfile, launchPitchM: pitch },
        formations: compile ? project.formations.map((f) => (f.role === 'launch' ? { ...f, points: [] } : f)) : project.formations,
      },
      playing: false,
    })
    if (compile) await get().recompile()
  },
  setShowCapsules: (v) => set({ showCapsules: v }),
  setAudienceView: (v) => set({ audienceView: v }),
  seekViolation: (v) => {
    set({ playing: false, playhead: v.time, selectedId: null })
  },

  renameFormation: (id, name) => {
    const { project } = get()
    if (!project) return
    set({
      project: {
        ...project,
        formations: project.formations.map((f) => (f.id === id ? { ...f, name } : f)),
        assets: project.assets.map((a) => {
          const f = project.formations.find((x) => x.id === id)
          return f && a.id === f.sourceAssetId ? { ...a, name } : a
        }),
      },
    })
  },
}))

export type { TransitionType }
