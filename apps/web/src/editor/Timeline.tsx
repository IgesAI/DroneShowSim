'use client'

import { useEffect, useRef, useState } from 'react'
import { useEditor } from './store'

function smpte(seconds: number, fps = 30) {
  const total = Math.max(0, Math.round(seconds * fps))
  const f = total % fps
  const s = Math.floor(total / fps) % 60
  const m = Math.floor(total / fps / 60) % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `00:${pad(m)}:${pad(s)}:${pad(f)}`
}

const btn = 'grid h-8 w-8 place-items-center rounded-full border border-white/10 text-[11px] text-gray-300 hover:border-indigo-400/50 hover:text-white disabled:opacity-30'

type Drag =
  | { kind: 'cue'; formationId: string; from: number }
  | { kind: 'resize'; formationId: string; startX: number; startHold: number }
  | { kind: 'anim'; id: string; startX: number; startOffset: number; hold: number }

export function Timeline() {
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const playing = useEditor((s) => s.playing)
  const loop = useEditor((s) => s.loop)
  const selectedId = useEditor((s) => s.selectedId)
  const setPlayhead = useEditor((s) => s.setPlayhead)
  const play = useEditor((s) => s.play)
  const pause = useEditor((s) => s.pause)
  const rewind = useEditor((s) => s.rewind)
  const skipCue = useEditor((s) => s.skipCue)
  const stepFrame = useEditor((s) => s.stepFrame)
  const setLoop = useEditor((s) => s.setLoop)
  const select = useEditor((s) => s.select)
  const reorderCue = useEditor((s) => s.reorderCue)
  const patchHold = useEditor((s) => s.patchHold)
  const patchAnimation = useEditor((s) => s.patchAnimation)
  const trackRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const moved = useRef(false)
  const dragRef = useRef<Drag | null>(null)
  dragRef.current = drag
  const projectRef = useRef(project)
  projectRef.current = project

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const current = dragRef.current
      const show = projectRef.current
      if (!current || !show) return
      const span = Math.max(show.timeline.duration, 0.001)
      moved.current = true
      if (current.kind === 'cue') {
        const rect = trackRef.current?.getBoundingClientRect()
        if (!rect) return
        const t = ((e.clientX - rect.left) / rect.width) * span
        const idx = show.timeline.cues.reduce((best, c, i) => {
          const mid = c.startTime + c.holdDuration / 2
          const other = show.timeline.cues[best]
          return Math.abs(t - mid) < Math.abs(t - (other.startTime + other.holdDuration / 2)) ? i : best
        }, 0)
        setHoverIndex(idx)
      }
      if (current.kind === 'resize') {
        const rect = trackRef.current?.getBoundingClientRect()
        if (!rect) return
        const dt = ((e.clientX - current.startX) / rect.width) * span
        void patchHold(current.formationId, current.startHold + dt, false)
      }
      if (current.kind === 'anim') {
        const rect = trackRef.current?.getBoundingClientRect()
        if (!rect) return
        const dt = ((e.clientX - current.startX) / rect.width) * span
        void patchAnimation(current.id, { cueOffset: Math.max(0, Math.min(current.hold - 0.4, current.startOffset + dt)) }, false)
      }
    }
    const onUp = () => {
      const current = dragRef.current
      const show = projectRef.current
      if (current?.kind === 'cue' && hoverIndex !== null) void reorderCue(current.formationId, hoverIndex)
      if (current?.kind === 'resize' && show) {
        const hold = show.timeline.cues.find((c) => c.formationId === current.formationId)?.holdDuration ?? 5
        void patchHold(current.formationId, hold, true)
      }
      if (current?.kind === 'anim') void patchAnimation(current.id, {}, true)
      setDrag(null)
      setHoverIndex(null)
      setTimeout(() => {
        moved.current = false
      }, 0)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [hoverIndex, patchAnimation, patchHold, reorderCue])

  if (!project) return null
  const duration = Math.max(project.timeline.duration, 0.001)
  const fmap = Object.fromEntries(project.formations.map((f) => [f.id, f]))
  const animations = project.timeline.animations ?? []

  return (
    <div className="border-t border-white/10 glass">
      <div className="flex items-center gap-2 px-4 py-2">
        <button type="button" title="Rewind (Home)" className={btn} onClick={rewind}>⏮</button>
        <button type="button" title="Previous cue (J)" className={btn} onClick={() => skipCue(-1)}>◀◀</button>
        <button type="button" title="Step back (←)" className={btn} onClick={() => stepFrame(-1)}>‹</button>
        <button type="button" title="Pause (K)" className={btn} disabled={!playing} onClick={pause}>❚❚</button>
        <button type="button" title="Play (Space)" onClick={play} className="glow-btn grid h-9 w-9 place-items-center rounded-full bg-indigo-600 text-white disabled:opacity-40" disabled={playing}>
          ▶
        </button>
        <button type="button" title="Step forward (→)" className={btn} onClick={() => stepFrame(1)}>›</button>
        <button type="button" title="Next cue (L)" className={btn} onClick={() => skipCue(1)}>▶▶</button>
        <button type="button" title="Loop" onClick={() => setLoop(!loop)} className={`${btn} ${loop ? 'border-indigo-400 text-indigo-300' : ''}`}>
          ⟳
        </button>
        <div className="ml-2 font-mono text-sm text-white">{smpte(playhead)}</div>
        <div className="text-gray-500">/</div>
        <div className="font-mono text-sm text-gray-400">{smpte(duration)}</div>
        <div className="ml-auto hidden text-[10px] text-gray-500 xl:block">drag clips · edge resizes hold · Del deletes</div>
      </div>
      <div
        ref={trackRef}
        className="relative mx-4 mb-3 h-[104px] cursor-pointer rounded-2xl bg-gray-950/80"
        onClick={(e) => {
          if (moved.current) return
          const rect = e.currentTarget.getBoundingClientRect()
          setPlayhead(((e.clientX - rect.left) / rect.width) * duration)
        }}
      >
        {project.timeline.cues.map((cue, i) => {
          const f = fmap[cue.formationId]
          const left = (cue.startTime / duration) * 100
          const width = (cue.holdDuration / duration) * 100
          const on = selectedId === f?.id || hoverIndex === i
          return (
            <div
              key={cue.id}
              className="absolute top-2 h-8 overflow-hidden rounded-lg border text-left text-[11px] text-white"
              style={{ left: `${left}%`, width: `${Math.max(width, 2)}%`, borderColor: on ? '#818cf8' : 'rgb(255 255 255 / 0.1)', background: hoverIndex === i ? 'rgb(129 140 248 / 0.28)' : 'rgb(79 70 229 / 0.15)' }}
              onPointerDown={(e) => {
                e.stopPropagation()
                e.currentTarget.setPointerCapture(e.pointerId)
                select(f?.id ?? null)
                setPlayhead(cue.startTime + 0.2)
                const locked = cue.phase === 'takeoff' || cue.phase === 'landing'
                const handle = e.nativeEvent.offsetX > e.currentTarget.offsetWidth - 10
                moved.current = false
                if (locked) return
                setDrag(
                  handle
                    ? { kind: 'resize', formationId: cue.formationId, startX: e.clientX, startHold: cue.holdDuration }
                    : { kind: 'cue', formationId: cue.formationId, from: i },
                )
              }}
            >
              <div className="pointer-events-none truncate px-2 pt-1.5">{cue.phase === 'takeoff' ? 'TAKEOFF' : cue.phase === 'landing' ? 'LAND' : (f?.name ?? cue.formationId)}</div>
              <div className="absolute right-0 top-0 h-full w-2 cursor-ew-resize bg-indigo-300/30" />
            </div>
          )
        })}
        {project.timeline.transitions.map((tr) => (
          <button
            key={tr.id}
            type="button"
            className="absolute top-[44px] h-4 overflow-hidden rounded-md border border-white/10 px-1 text-[9px] uppercase tracking-wide text-gray-400"
            style={{ left: `${(tr.startTime / duration) * 100}%`, width: `${(tr.duration / duration) * 100}%` }}
            onClick={(e) => {
              e.stopPropagation()
              select(tr.id)
              setPlayhead(tr.startTime + tr.duration * 0.45)
            }}
          >
            {tr.type} {tr.duration.toFixed(1)}s
          </button>
        ))}
        {animations.map((anim) => {
          const host = project.timeline.cues.find((c) => c.formationId === anim.formationId)
          const start = host ? host.startTime + anim.cueOffset : anim.startTime
          return (
            <div
              key={anim.id}
              className="absolute top-[66px] h-6 cursor-grab overflow-hidden rounded-md border border-fuchsia-400/40 bg-fuchsia-500/15 px-1 text-[10px] text-fuchsia-100"
              style={{ left: `${(start / duration) * 100}%`, width: `${(anim.duration / duration) * 100}%` }}
              onPointerDown={(e) => {
                e.stopPropagation()
                e.currentTarget.setPointerCapture(e.pointerId)
                select(anim.id)
                setPlayhead(start + 0.15)
                moved.current = false
                setDrag({ kind: 'anim', id: anim.id, startX: e.clientX, startOffset: anim.cueOffset, hold: host?.holdDuration ?? 6 })
              }}
            >
              {anim.name}
            </div>
          )
        })}
        <div className="pointer-events-none absolute top-0 h-full w-px bg-indigo-400" style={{ left: `${(playhead / duration) * 100}%` }} />
      </div>
    </div>
  )
}
