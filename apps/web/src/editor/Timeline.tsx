'use client'

import { useEffect, useRef, useState } from 'react'
import { useEditor } from './store'
import { rulerTime } from './ui'

type Drag =
  | { kind: 'cue'; formationId: string; from: number }
  | { kind: 'resize'; formationId: string; startX: number; startHold: number }
  | { kind: 'anim'; id: string; startX: number; startOffset: number; hold: number }

const TRACKS = [
  { id: 'form', label: 'FORM', h: 24 },
  { id: 'xfr', label: 'XFRM', h: 16 },
  { id: 'lite', label: 'LITE', h: 16 },
  { id: 'aud', label: 'AUD', h: 8 },
  { id: 'cue', label: 'CUE', h: 8 },
  { id: 'safe', label: 'SAFE', h: 8 },
] as const

const TRACK_H = TRACKS.reduce((s, t) => s + t.h, 0)
const TOP = {
  form: 0,
  xfr: 24,
  lite: 40,
  aud: 56,
  cue: 64,
  safe: 72,
}

export function Timeline() {
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const selectedId = useEditor((s) => s.selectedId)
  const violations = useEditor((s) => s.violations)
  const setPlayhead = useEditor((s) => s.setPlayhead)
  const select = useEditor((s) => s.select)
  const reorderCue = useEditor((s) => s.reorderCue)
  const patchHold = useEditor((s) => s.patchHold)
  const patchAnimation = useEditor((s) => s.patchAnimation)
  const seekViolation = useEditor((s) => s.seekViolation)
  const trackRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const [zoom, setZoom] = useState(1)
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
      const rect = trackRef.current?.getBoundingClientRect()
      if (!rect) return
      if (current.kind === 'cue') {
        const t = ((e.clientX - rect.left) / rect.width) * span
        const idx = show.timeline.cues.reduce((best, c, i) => {
          const mid = c.startTime + c.holdDuration / 2
          const other = show.timeline.cues[best]
          return Math.abs(t - mid) < Math.abs(t - (other.startTime + other.holdDuration / 2)) ? i : best
        }, 0)
        setHoverIndex(idx)
      }
      if (current.kind === 'resize') {
        const dt = ((e.clientX - current.startX) / rect.width) * span
        const snapped = Math.round((current.startHold + dt) * 10) / 10
        void patchHold(current.formationId, snapped, false)
      }
      if (current.kind === 'anim') {
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

  if (!project || project.timeline.cues.length === 0) {
    return (
      <div className="flex h-[104px] shrink-0 items-center bg-chrome px-2 text-[12px] text-faint">
        Drag a formation onto the timeline to begin the show.
      </div>
    )
  }

  const duration = Math.max(project.timeline.duration, 0.001)
  const fmap = Object.fromEntries(project.formations.map((f) => [f.id, f]))
  const animations = project.timeline.animations ?? []
  const ticks = Math.min(8, Math.max(4, Math.round(duration / 30)))

  const seek = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect) return
    setPlayhead(((clientX - rect.left) / rect.width) * duration)
  }

  return (
    <div className="shrink-0 bg-chrome">
      <div className="flex">
        <div className="w-16 shrink-0 bg-panel">
          <div className="flex h-6 items-center justify-between px-2 text-[11px] text-faint">
            <button type="button" className="h-4 w-4 hover:text-ink" onClick={() => setZoom((z) => Math.max(1, z - 0.5))}>
              −
            </button>
            <span className="num w-6 text-center">{zoom.toFixed(1)}</span>
            <button type="button" className="h-4 w-4 hover:text-ink" onClick={() => setZoom((z) => Math.min(4, z + 0.5))}>
              +
            </button>
          </div>
          {TRACKS.map((t, i) => (
            <div
              key={t.id}
              className={`flex items-center px-2 text-[11px] text-faint ${i % 2 ? 'bg-canvas/50' : ''}`}
              style={{ height: t.h }}
            >
              {t.label}
            </div>
          ))}
        </div>
        <div className="ui-scroll min-w-0 flex-1 overflow-x-auto">
          <div style={{ width: `${zoom * 100}%`, minWidth: '100%' }}>
            <div className="relative h-6">
              {Array.from({ length: ticks + 1 }, (_, i) => {
                const t = (i / ticks) * duration
                const edge = i === 0 || i === ticks
                return (
                  <div
                    key={i}
                    className="absolute top-0 h-full"
                    style={{ left: `${(i / ticks) * 100}%`, transform: edge ? undefined : 'translateX(-50%)' }}
                  >
                    <div className="h-1 w-px bg-line-strong" />
                    <div className={`num text-[11px] text-faint ${i === ticks ? 'pr-1 text-right' : ''}`}>{rulerTime(t)}</div>
                  </div>
                )
              })}
            </div>
            <div
              ref={trackRef}
              className="relative cursor-pointer"
              style={{ height: TRACK_H }}
              onClick={(e) => {
                if (moved.current) return
                seek(e.clientX)
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                const id = e.dataTransfer.getData('text/lumina-asset')
                if (!id) return
                const f = project.formations.find((x) => x.sourceAssetId === id)
                if (!f) return
                const cue = project.timeline.cues.find((c) => c.formationId === f.id)
                select(f.id)
                if (cue) setPlayhead(cue.startTime + 0.2)
              }}
            >
              {TRACKS.map((t, i) => (
                <div
                  key={t.id}
                  className={`absolute right-0 left-0 ${i % 2 ? 'bg-canvas/50' : ''}`}
                  style={{ top: Object.values(TOP)[i], height: t.h }}
                />
              ))}

              {project.timeline.cues.map((cue, i) => {
                const f = fmap[cue.formationId]
                const left = (cue.startTime / duration) * 100
                const width = (cue.holdDuration / duration) * 100
                const on = selectedId === f?.id || hoverIndex === i
                const locked = cue.phase === 'takeoff' || cue.phase === 'landing'
                const name = cue.phase === 'takeoff' ? 'Takeoff' : cue.phase === 'landing' ? 'Land' : (f?.name ?? cue.formationId)
                return (
                  <div
                    key={cue.id}
                    className="absolute overflow-hidden text-left text-[11px] text-ink"
                    style={{
                      top: TOP.form + 2,
                      height: 20,
                      left: `${left}%`,
                      width: `${Math.max(width, 1.2)}%`,
                      background: on ? 'rgb(210 122 58 / 0.28)' : 'rgb(255 255 255 / 0.14)',
                      boxShadow: on ? 'inset 2px 0 0 #d27a3a' : undefined,
                    }}
                    onPointerDown={(e) => {
                      e.stopPropagation()
                      e.currentTarget.setPointerCapture(e.pointerId)
                      select(f?.id ?? null)
                      setPlayhead(cue.startTime + 0.2)
                      const handle = e.nativeEvent.offsetX > e.currentTarget.offsetWidth - 8
                      moved.current = false
                      if (locked) return
                      setDrag(
                        handle
                          ? { kind: 'resize', formationId: cue.formationId, startX: e.clientX, startHold: cue.holdDuration }
                          : { kind: 'cue', formationId: cue.formationId, from: i },
                      )
                    }}
                  >
                    <div className="pointer-events-none truncate px-1 leading-5">{name}</div>
                    {on && !locked && <div className="absolute right-0 top-0 h-full w-1 cursor-ew-resize bg-ink/30" />}
                  </div>
                )
              })}

              {project.timeline.transitions.map((tr) => {
                const on = selectedId === tr.id
                return (
                  <button
                    key={tr.id}
                    type="button"
                    className="absolute overflow-hidden text-left text-[11px] text-mute"
                    style={{
                      top: TOP.xfr + 2,
                      height: 12,
                      left: `${(tr.startTime / duration) * 100}%`,
                      width: `${Math.max((tr.duration / duration) * 100, 0.8)}%`,
                      background: on ? 'rgb(210 122 58 / 0.22)' : 'rgb(255 255 255 / 0.08)',
                      boxShadow: on ? 'inset 2px 0 0 #d27a3a' : undefined,
                    }}
                    onClick={(e) => {
                      e.stopPropagation()
                      select(tr.id)
                      setPlayhead(tr.startTime + tr.duration * 0.45)
                    }}
                  >
                    <span className="px-1">{tr.type}</span>
                  </button>
                )
              })}

              {animations.map((anim) => {
                const host = project.timeline.cues.find((c) => c.formationId === anim.formationId)
                const start = host ? host.startTime + anim.cueOffset : anim.startTime
                const on = selectedId === anim.id
                return (
                  <div
                    key={anim.id}
                    className="absolute cursor-grab overflow-hidden px-1 text-[11px] text-ink"
                    style={{
                      top: TOP.lite + 2,
                      height: 12,
                      left: `${(start / duration) * 100}%`,
                      width: `${Math.max((anim.duration / duration) * 100, 0.8)}%`,
                      background: 'rgb(255 255 255 / 0.10)',
                      boxShadow: on ? 'inset 2px 0 0 #d27a3a' : undefined,
                    }}
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

              {project.timeline.cues.map((cue) => (
                <div
                  key={`evt-${cue.id}`}
                  className="absolute w-px bg-line-strong"
                  style={{ top: TOP.cue, height: 8, left: `${(cue.startTime / duration) * 100}%` }}
                  title={cue.phase}
                />
              ))}

              {violations
                .reduce((acc, v) => {
                  const prev = acc[acc.length - 1]
                  if (prev && Math.abs(v.time - prev.time) / duration < 0.005) {
                    if (v.severity === 'error') acc[acc.length - 1] = v
                    return acc
                  }
                  acc.push(v)
                  return acc
                }, [] as typeof violations)
                .map((v, i) => (
                  <button
                    key={`v-${v.time}-${i}`}
                    type="button"
                    title={`${v.severity === 'error' ? 'SEP' : 'WARN'} ${v.measured.toFixed(2)} m < ${v.required.toFixed(2)} m · ${v.droneIds.map((id) => `D${String(id).padStart(3, '0')}`).join('·')} @ ${v.time.toFixed(2)}s`}
                    className={`absolute h-1.5 w-0.5 ${v.severity === 'error' ? 'bg-hot' : 'bg-warn'}`}
                    style={{ top: TOP.safe + 1, left: `${(v.time / duration) * 100}%` }}
                    onClick={(e) => {
                      e.stopPropagation()
                      seekViolation(v)
                    }}
                  />
                ))}

              <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-accent" style={{ left: `${(playhead / duration) * 100}%` }}>
                <div className="absolute -top-1 -left-[3px] h-1.5 w-1.5 rotate-45 bg-accent" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
