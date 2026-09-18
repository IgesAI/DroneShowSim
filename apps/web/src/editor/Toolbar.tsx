'use client'

import { useEffect, useRef, useState } from 'react'
import { exportDshow, exportGenericCsv, exportSkybrush, exportVviz } from './api'
import { useEditor, type CameraPreset } from './store'
import { compilerPhase, flaggedDrones } from './domain'
import { GhostBtn, Icon, IconBtn, StatusMark, smpte } from './ui'

const VIEWS: { id: CameraPreset; label: string }[] = [
  { id: 'persp', label: 'Persp' },
  { id: 'top', label: 'Top' },
  { id: 'front', label: 'Front' },
  { id: 'side', label: 'Side' },
]

function failExport(err: unknown) {
  useEditor.setState({ error: err instanceof Error ? err.message : 'Export failed' })
}

export function Toolbar() {
  const project = useEditor((s) => s.project)
  const compiling = useEditor((s) => s.compiling)
  const dirty = useEditor((s) => s.dirty)
  const playing = useEditor((s) => s.playing)
  const loop = useEditor((s) => s.loop)
  const playhead = useEditor((s) => s.playhead)
  const cameraPreset = useEditor((s) => s.cameraPreset)
  const showGrid = useEditor((s) => s.showGrid)
  const showBounds = useEditor((s) => s.showBounds)
  const showCapsules = useEditor((s) => s.showCapsules)
  const showTrajectories = useEditor((s) => s.showTrajectories)
  const viewMode = useEditor((s) => s.viewMode)
  const audienceView = useEditor((s) => s.audienceView)
  const past = useEditor((s) => s.past)
  const future = useEditor((s) => s.future)
  const violations = useEditor((s) => s.violations)
  const [exportOpen, setExportOpen] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!exportRef.current?.contains(e.target as Node)) setExportOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [])

  const duration = project?.timeline.duration ?? 0
  const n = project?.droneProfile.count ?? 0
  const phase = compilerPhase({ project, compiling, dirty, violations })
  const flagged = flaggedDrones(violations)
  const ready = Math.max(0, n - flagged.size)

  return (
    <header className="flex h-8 shrink-0 items-center gap-4 whitespace-nowrap bg-chrome px-2">
      <div className="flex min-w-0 items-center gap-2">
        <input
          aria-label="Project name"
          className="h-6 w-[128px] min-w-[72px] bg-transparent px-1 text-[13px] text-ink hover:bg-hover"
          value={project?.name ?? 'Untitled'}
          onChange={(e) => useEditor.getState().renameProject(e.target.value)}
        />
        <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-mute" title="Compiler state">
          <StatusMark tone={phase.tone} />
          {phase.phase}
        </span>
      </div>

      <div className="flex items-center">
        <IconBtn title="Undo (Ctrl+Z)" disabled={!past.length} onClick={() => useEditor.getState().undo()}>
          {Icon.undo}
        </IconBtn>
        <IconBtn title="Redo (Ctrl+Y)" disabled={!future.length} onClick={() => useEditor.getState().redo()}>
          {Icon.redo}
        </IconBtn>
      </div>

      <div className="flex h-6 items-center">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => useEditor.getState().setCameraPreset(v.id)}
            className={`h-6 px-2 text-[12px] ${cameraPreset === v.id ? 'bg-hover text-ink shadow-[inset_0_-2px_0_#d27a3a]' : 'text-faint hover:text-ink'}`}
          >
            {v.label}
          </button>
        ))}
        <button
          type="button"
          title="Audience view"
          onClick={() => useEditor.getState().setAudienceView(!audienceView)}
          className={`h-6 px-2 text-[12px] ${audienceView ? 'bg-hover text-ink shadow-[inset_0_-2px_0_#d27a3a]' : 'text-faint hover:text-ink'}`}
        >
          Audience
        </button>
      </div>

      <div className="flex items-center">
        <IconBtn title="Grid" active={showGrid} onClick={() => useEditor.getState().setShowGrid(!showGrid)}>
          {Icon.grid}
        </IconBtn>
        <IconBtn title="Show bounds" active={showBounds} onClick={() => useEditor.getState().setShowBounds(!showBounds)}>
          {Icon.bounds}
        </IconBtn>
        <IconBtn title="Safety capsules" active={showCapsules} onClick={() => useEditor.getState().setShowCapsules(!showCapsules)}>
          {Icon.capsule}
        </IconBtn>
        <IconBtn
          title="Velocity trajectories"
          active={showTrajectories}
          onClick={() => useEditor.getState().setShowTrajectories(!showTrajectories)}
        >
          {Icon.path}
        </IconBtn>
        <button
          type="button"
          title="Engineering view — every physical drone, coloured by role (E)"
          onClick={() => useEditor.getState().setViewMode(viewMode === 'engineering' ? 'show' : 'engineering')}
          className={`h-6 px-2 text-[12px] ${viewMode === 'engineering' ? 'bg-hover text-ink shadow-[inset_0_-2px_0_#d27a3a]' : 'text-faint hover:text-ink'}`}
        >
          Eng
        </button>
      </div>

      <div className="flex items-center">
        <IconBtn title="Rewind (Home)" onClick={() => useEditor.getState().rewind()}>
          {Icon.rewind}
        </IconBtn>
        <IconBtn title="Previous cue (J)" onClick={() => useEditor.getState().skipCue(-1)}>
          {Icon.prev}
        </IconBtn>
        <IconBtn title="Step back" onClick={() => useEditor.getState().stepFrame(-1)}>
          {Icon.stepBack}
        </IconBtn>
        <button
          type="button"
          title={playing ? 'Pause (Space)' : 'Play (Space)'}
          onClick={() => (playing ? useEditor.getState().pause() : useEditor.getState().play())}
          className="grid h-6 w-6 place-items-center rounded-[2px] bg-accent text-[#1a120c]"
        >
          {playing ? Icon.pause : Icon.play}
        </button>
        <IconBtn title="Step forward" onClick={() => useEditor.getState().stepFrame(1)}>
          {Icon.stepFwd}
        </IconBtn>
        <IconBtn title="Next cue (L)" onClick={() => useEditor.getState().skipCue(1)}>
          {Icon.next}
        </IconBtn>
        <IconBtn title="Loop" active={loop} onClick={() => useEditor.getState().setLoop(!loop)}>
          {Icon.loop}
        </IconBtn>
        <span className="num ml-2 text-[11px] text-ink">{smpte(playhead)}</span>
        <span className="num text-[11px] text-faint">/{smpte(duration)}</span>
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        {project && (
          <span className="num text-[11px] text-mute" title="Flight-ready drones">
            {compiling
              ? `Resolving trajectories · ${n}`
              : flagged.size === 0
                ? `${n} / ${n} flight paths valid`
                : `${ready} / ${n} flight-ready`}
            {flagged.size > 0 && <span className="ml-2 text-hot">{flagged.size} flagged</span>}
          </span>
        )}
        <GhostBtn disabled={!project || compiling} onClick={() => void useEditor.getState().validate()}>
          Validate
        </GhostBtn>
        <div ref={exportRef} className="relative">
          <GhostBtn disabled={!project} onClick={() => setExportOpen((v) => !v)}>
            Export
          </GhostBtn>
          {exportOpen && project && (
            <div className="absolute right-0 top-8 z-30 w-40 bg-raised py-1">
              {(
                [
                  { label: '.dshow', run: () => exportDshow(project) },
                  { label: 'Generic CSV', run: () => exportGenericCsv(project) },
                  { label: 'VVIZ', run: () => exportVviz(project) },
                  { label: 'Skybrush CSV', run: () => exportSkybrush(project) },
                ] as const
              ).map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="block h-6 w-full px-2 text-left text-[12px] text-mute hover:bg-hover hover:text-ink"
                  onClick={() => {
                    setExportOpen(false)
                    void item.run().catch(failExport)
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
