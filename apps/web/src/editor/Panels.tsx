'use client'

import type { AnimationMotion, TransitionType } from '@lumina/schema'
import { useEffect, useState } from 'react'
import { exportDshow, exportGenericCsv, exportSkybrush, exportVviz } from './api'
import { acceptFiles, readAssetFile } from './assets'
import { useEditor } from './store'

const MOTIONS: { id: AnimationMotion; label: string }[] = [
  { id: 'backflip', label: 'Backflip' },
  { id: 'orbit', label: 'Orbit' },
  { id: 'advance', label: 'Advance' },
  { id: 'wave', label: 'Wave' },
  { id: 'pulse', label: 'Pulse' },
  { id: 'chroma', label: 'Chroma' },
]

const TRANSITIONS: TransitionType[] = ['morph', 'direct', 'explode', 'orbit', 'wave']

function failExport(err: unknown) {
  useEditor.setState({ error: err instanceof Error ? err.message : 'Export failed' })
}

export function LeftPanel() {
  const project = useEditor((s) => s.project)
  const compiling = useEditor((s) => s.compiling)
  const selectedId = useEditor((s) => s.selectedId)
  const loadDemo = useEditor((s) => s.loadDemo)
  const patchCount = useEditor((s) => s.patchCount)
  const importAsset = useEditor((s) => s.importAsset)
  const addAnimation = useEditor((s) => s.addAnimation)
  const patchPitch = useEditor((s) => s.patchPitch)
  const pitch = project?.droneProfile.launchPitchM ?? 4
  const select = useEditor((s) => s.select)
  const removeAsset = useEditor((s) => s.removeAsset)
  const count = project?.droneProfile.count ?? 80
  const [draftCount, setDraftCount] = useState(count)
  useEffect(() => {
    setDraftCount(count)
  }, [count])
  const selectedFormation =
    project?.formations.find((f) => f.id === selectedId) ??
    project?.formations.find((f) => f.sourceAssetId === selectedId) ??
    project?.formations.find((f) => f.id === project.timeline.animations.find((a) => a.id === selectedId)?.formationId)

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-white/10 glass">
      <div className="border-b border-white/10 px-4 py-3">
        <div className="text-[11px] uppercase tracking-wide text-gray-400">Project</div>
        <div className="font-[family-name:var(--font-display)] text-sm text-white">{project?.name ?? 'Cobra demo'}</div>
      </div>
      <div className="space-y-4 overflow-y-auto p-4 text-sm">
        <button type="button" onClick={() => void loadDemo(count)} className="glow-btn w-full rounded-full bg-indigo-600 px-4 py-2 text-left text-sm text-white hover:bg-indigo-500">
          Load Cobra demo
        </button>
        <label className="block">
          <div className="mb-1 flex justify-between text-[11px] uppercase tracking-wide text-gray-400">
            <span>Drones</span><span className="text-white">{draftCount}</span>
          </div>
          <input
            type="range"
            min={10}
            max={500}
            step={10}
            value={draftCount}
            onChange={(e) => setDraftCount(Number(e.target.value))}
            onPointerUp={() => {
              if (draftCount !== count) void patchCount(draftCount)
            }}
            className="w-full"
          />
        </label>
        <label className="block">
          <div className="mb-1 flex justify-between text-[11px] uppercase tracking-wide text-gray-400">
            <span>Pad pitch</span><span className="text-white">{pitch.toFixed(1)} m</span>
          </div>
          <input
            type="range"
            min={2}
            max={10}
            step={0.1}
            value={pitch}
            onChange={(e) => void patchPitch(Number(e.target.value), false)}
            onPointerUp={() => void patchPitch(pitch, true)}
            className="w-full"
          />
        </label>
        <div className="text-[11px] uppercase tracking-wide text-gray-400">Assets</div>
        <label className="block cursor-pointer rounded-2xl border border-dashed border-indigo-400/40 bg-indigo-500/5 px-3 py-3 text-xs text-indigo-100 hover:border-indigo-300">
          <div className="font-medium text-white">Upload formation</div>
          <div className="mt-0.5 text-[11px] text-gray-400">SVG, GLB, OBJ, or STL — 3D models become volumetric swarms</div>
          <input
            type="file"
            accept={acceptFiles()}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (!file) return
              void readAssetFile(file)
                .then(({ name, kind, content }) => importAsset(name, content, kind))
                .catch((err) => useEditor.setState({ error: err instanceof Error ? err.message : 'Import failed' }))
              e.target.value = ''
            }}
          />
        </label>
        <ul className="space-y-1">
          {(project?.assets ?? []).map((a) => {
            const on = selectedId === a.id || selectedFormation?.sourceAssetId === a.id
            return (
              <li key={a.id} className={`flex items-center gap-1 rounded-lg px-1.5 py-1 text-xs ${on ? 'bg-indigo-500/15 text-white' : 'text-gray-400'}`}>
                <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => {
                  const f = project?.formations.find((x) => x.sourceAssetId === a.id)
                  select(f?.id ?? a.id)
                }}>
                  {a.name} · {a.kind}
                </button>
                <button
                  type="button"
                  title="Delete asset"
                  className="rounded-full px-1.5 text-gray-500 hover:bg-rose-500/20 hover:text-rose-300"
                  onClick={() => void removeAsset(a.id)}
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
        <div className="text-[11px] uppercase tracking-wide text-gray-400">Animate selected</div>
        <div className="grid grid-cols-2 gap-1.5">
          {MOTIONS.map((m) => (
            <button
              key={m.id}
              type="button"
              disabled={!selectedFormation}
              onClick={() => selectedFormation && addAnimation(selectedFormation.id, m.id)}
              className="rounded-full border border-white/10 px-2 py-1.5 text-left text-[11px] text-gray-300 hover:border-indigo-400/40 disabled:opacity-30"
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="text-[11px] leading-relaxed text-gray-400">
          {compiling ? 'dshowc is compiling…' : 'Drones are volumes. Pad pitch is ground spacing; capsules grow with speed.'}
        </p>
      </div>
    </aside>
  )
}

export function RightPanel() {
  const project = useEditor((s) => s.project)
  const selectedId = useEditor((s) => s.selectedId)
  const removeSelected = useEditor((s) => s.removeSelected)
  const patchHold = useEditor((s) => s.patchHold)
  const patchAnimation = useEditor((s) => s.patchAnimation)
  const patchTransition = useEditor((s) => s.patchTransition)
  const renameFormation = useEditor((s) => s.renameFormation)
  const violations = useEditor((s) => s.violations)
  const seekViolation = useEditor((s) => s.seekViolation)
  const formation = project?.formations.find((f) => f.id === selectedId)
  const transition = project?.timeline.transitions.find((t) => t.id === selectedId)
  const animation = project?.timeline.animations.find((a) => a.id === selectedId)
  const cue = formation ? project?.timeline.cues.find((c) => c.formationId === formation.id) : undefined
  const profile = project?.droneProfile
  const swatches = formation
    ? [...new Set(formation.points.map((p) => p.color.map((c) => Math.round(c * 255)).join(',')))].slice(0, 8)
    : []

  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-l border-white/10 glass">
      <div className="border-b border-white/10 px-4 py-3">
        <div className="text-[11px] uppercase tracking-wide text-gray-400">Inspector</div>
        <div className="font-[family-name:var(--font-display)] text-sm text-white">
          {formation?.name ?? animation?.name ?? (transition ? `${transition.type} ${transition.duration.toFixed(1)}s` : 'Show')}
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-xs">
        {formation && cue && (
          <div className="space-y-3 text-gray-400">
            <label className="block">
              <div className="mb-1 uppercase tracking-wide">Name</div>
              <input
                className="w-full rounded-lg border border-white/10 bg-gray-950/80 px-2 py-1.5 text-white"
                value={formation.name}
                onChange={(e) => renameFormation(formation.id, e.target.value)}
              />
            </label>
            <label className="block">
              <div className="mb-1 flex justify-between uppercase tracking-wide">
                <span>Hold</span><span className="text-white">{cue.holdDuration.toFixed(1)}s</span>
              </div>
              <input
                type="range"
                min={1}
                max={20}
                step={0.1}
                value={cue.holdDuration}
                onChange={(e) => void patchHold(formation.id, Number(e.target.value), false)}
                onPointerUp={() => void patchHold(formation.id, cue.holdDuration, true)}
                className="w-full"
              />
            </label>
            <div>{formation.points.length} points · {formation.generationSettings.widthM}×{formation.generationSettings.heightM}m</div>
            {swatches.length > 0 && (
              <div>
                <div className="mb-1 uppercase tracking-wide">Sampled colors</div>
                <div className="flex gap-1">
                  {swatches.map((s) => {
                    const [r, g, b] = s.split(',').map(Number)
                    return <span key={s} className="h-4 w-4 rounded-full border border-white/20" style={{ background: `rgb(${r},${g},${b})` }} />
                  })}
                </div>
              </div>
            )}
          </div>
        )}
        {animation && (
          <div className="space-y-3 text-gray-400">
            <div>Motion {animation.motion} · {animation.kind}</div>
            <label className="block">
              <div className="mb-1 flex justify-between uppercase tracking-wide">
                <span>Cue offset</span><span className="text-white">+{animation.cueOffset.toFixed(1)}s</span>
              </div>
              <input
                type="range"
                min={0}
                max={12}
                step={0.1}
                value={animation.cueOffset}
                onChange={(e) => void patchAnimation(animation.id, { cueOffset: Number(e.target.value) }, false)}
                onPointerUp={() => void patchAnimation(animation.id, {}, true)}
                className="w-full"
              />
            </label>
            <label className="block">
              <div className="mb-1 flex justify-between uppercase tracking-wide">
                <span>Duration</span><span className="text-white">{animation.duration.toFixed(1)}s</span>
              </div>
              <input
                type="range"
                min={0.5}
                max={12}
                step={0.1}
                value={animation.duration}
                onChange={(e) => void patchAnimation(animation.id, { duration: Number(e.target.value) }, false)}
                onPointerUp={() => void patchAnimation(animation.id, {}, true)}
                className="w-full"
              />
            </label>
          </div>
        )}
        {transition && (
          <div className="space-y-3 text-gray-400">
            <label className="block">
              <div className="mb-1 uppercase tracking-wide">Style</div>
              <select
                className="w-full rounded-lg border border-white/10 bg-gray-950/80 px-2 py-1.5 text-white"
                value={transition.type}
                onChange={(e) => void patchTransition(transition.id, { type: e.target.value as TransitionType })}
              >
                {TRANSITIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <div className="mb-1 flex justify-between uppercase tracking-wide">
                <span>Duration</span><span className="text-white">{transition.duration.toFixed(1)}s · {transition.durationMode}</span>
              </div>
              <input
                type="range"
                min={1}
                max={20}
                step={0.1}
                value={transition.duration}
                onChange={(e) => void patchTransition(transition.id, { duration: Number(e.target.value), durationMode: 'manual' }, false)}
                onPointerUp={() => void patchTransition(transition.id, { durationMode: 'manual' }, true)}
                className="w-full"
              />
            </label>
            <div>Assignments {transition.assignment.length}</div>
          </div>
        )}
        {profile && (
          <div className="rounded-2xl border border-white/10 bg-gray-900/60 p-3 text-[11px] text-gray-400">
            <div>min sep {profile.minimumSeparationM}m + 2×r + nav/wind</div>
            <div>horiz {profile.maxHorizontalSpeedMps} · up {profile.maxAscentSpeedMps} · down {profile.maxDescentSpeedMps}</div>
            <div>jerk {profile.maxJerkMps3} · GNSS {project?.safetyProfile.gnssMode}</div>
          </div>
        )}
        {violations.length > 0 && (
          <div>
            <div className="mb-1 uppercase tracking-wide text-rose-300">Capsule warnings</div>
            <ul className="max-h-32 space-y-1 overflow-y-auto">
              {violations.slice(0, 12).map((v, i) => (
                <li key={`${v.time}-${i}`}>
                  <button type="button" className="w-full rounded-lg border border-rose-400/20 px-2 py-1 text-left text-[10px] text-rose-200 hover:bg-rose-500/10" onClick={() => seekViolation(v)}>
                    {v.message}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(project?.compilerNotes ?? []).length > 0 && (
          <div className="space-y-1 text-[10px] text-amber-200/80">
            {project?.compilerNotes.slice(0, 6).map((n, i) => (
              <div key={i}>{n.message}</div>
            ))}
          </div>
        )}
        {(formation || animation) && formation?.role !== 'launch' && (
          <button type="button" onClick={() => void removeSelected()} className="w-full rounded-full border border-rose-400/30 px-3 py-2 text-left text-rose-300 hover:bg-rose-500/10">
            Delete selected
          </button>
        )}
      </div>
      <div className="space-y-2 border-t border-white/10 p-4">
        <button type="button" disabled={!project} onClick={() => project && void exportDshow(project).catch(failExport)} className="w-full rounded-full border border-white/10 px-3 py-2 text-left text-xs text-gray-200">Export .dshow</button>
        <button type="button" disabled={!project} onClick={() => project && void exportGenericCsv(project).catch(failExport)} className="w-full rounded-full border border-white/10 px-3 py-2 text-left text-xs text-gray-200">Export generic CSV</button>
        <button type="button" disabled={!project} onClick={() => project && void exportVviz(project).catch(failExport)} className="w-full rounded-full border border-white/10 px-3 py-2 text-left text-xs text-gray-200">Export VVIZ (viz only)</button>
        <button type="button" disabled={!project} onClick={() => project && void exportSkybrush(project).catch(failExport)} className="glow-btn w-full rounded-full bg-indigo-600 px-3 py-2 text-left text-xs text-white">Export Skybrush CSV.zip</button>
      </div>
    </aside>
  )
}
