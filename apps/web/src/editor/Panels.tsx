'use client'

import type { AnimationMotion, TransitionType } from '@lumina/schema'
import { useEffect, useMemo, useState } from 'react'
import { acceptFiles, readAssetFile } from './assets'
import { droneBudget, droneLabel, formationEnvelope, formationQuality, requiredSep, transitionStats } from './domain'
import { useEditor } from './store'
import { Field, PropertyRow, Section, StatusMark } from './ui'

const MOTIONS: { id: AnimationMotion; label: string }[] = [
  { id: 'backflip', label: 'Backflip' },
  { id: 'orbit', label: 'Orbit' },
  { id: 'advance', label: 'Advance' },
  { id: 'wave', label: 'Wave' },
  { id: 'pulse', label: 'Pulse' },
  { id: 'chroma', label: 'Chroma' },
]

const TRANSITIONS: TransitionType[] = ['morph', 'direct', 'explode', 'orbit', 'wave']

const PRIMS: { id: string; label: string; svg: string }[] = [
  {
    id: 'circle',
    label: 'Circle',
    svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="38" fill="none" stroke="#fff" stroke-width="5"/></svg>',
  },
  {
    id: 'square',
    label: 'Square',
    svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="14" y="14" width="72" height="72" fill="none" stroke="#fff" stroke-width="5"/></svg>',
  },
  {
    id: 'line',
    label: 'Line',
    svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M8 50 H92" fill="none" stroke="#fff" stroke-width="6"/></svg>',
  },
  {
    id: 'triangle',
    label: 'Triangle',
    svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 12 L88 86 H12 Z" fill="none" stroke="#fff" stroke-width="5"/></svg>',
  },
]

function AxisGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" className="shrink-0">
      <path d="M2 12 H12" stroke="#c44a44" strokeWidth="1.1" />
      <path d="M2 12 V2" stroke="#3f9d6a" strokeWidth="1.1" />
      <path d="M2 12 L10 4" stroke="#5b8def" strokeWidth="1.1" />
    </svg>
  )
}

function QuietBtn({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-6 px-1 text-left text-[12px] text-mute hover:text-ink disabled:opacity-30"
    >
      {children}
    </button>
  )
}

export function LeftPanel() {
  const project = useEditor((s) => s.project)
  const compiling = useEditor((s) => s.compiling)
  const selectedId = useEditor((s) => s.selectedId)
  const loadDemo = useEditor((s) => s.loadDemo)
  const patchCount = useEditor((s) => s.patchCount)
  const importAsset = useEditor((s) => s.importAsset)
  const addAnimation = useEditor((s) => s.addAnimation)
  const addText = useEditor((s) => s.addText)
  const patchPitch = useEditor((s) => s.patchPitch)
  const converting = useEditor((s) => s.conversion) !== null
  const pitch = project?.droneProfile.launchPitchM ?? 4
  const select = useEditor((s) => s.select)
  const removeAsset = useEditor((s) => s.removeAsset)
  const count = project?.droneProfile.count ?? 80
  const [draftCount, setDraftCount] = useState(count)
  const [query, setQuery] = useState('')
  const [text, setText] = useState('')
  useEffect(() => {
    setDraftCount(count)
  }, [count])

  const selectedFormation =
    project?.formations.find((f) => f.id === selectedId) ??
    project?.formations.find((f) => f.sourceAssetId === selectedId) ??
    project?.formations.find((f) => f.id === project.timeline.animations.find((a) => a.id === selectedId)?.formationId)

  const assets = useMemo(() => {
    const list = project?.assets ?? []
    const q = query.trim().toLowerCase()
    return q ? list.filter((a) => a.name.toLowerCase().includes(q) || a.kind.includes(q)) : list
  }, [project?.assets, query])

  const importFile = (file: File) => {
    if (converting) return
    void readAssetFile(file)
      .then(({ name, kind, content }) => importAsset(name, content, kind))
      .catch((err) => useEditor.setState({ error: err instanceof Error ? err.message : 'Import failed' }))
  }

  return (
    <aside className="flex w-[224px] shrink-0 flex-col bg-chrome">
      <Section title="Fleet">
        <PropertyRow label="Drones">
          <Field type="number" value={draftCount} onChange={(v) => setDraftCount(Number(v) || 0)} />
        </PropertyRow>
        <div className="flex h-4 items-center">
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
          />
        </div>
        <PropertyRow label="Pad pitch" unit="m">
          <Field type="number" value={pitch.toFixed(1)} onChange={(v) => void patchPitch(Number(v), false)} />
        </PropertyRow>
        <div className="flex h-4 items-center">
          <input
            type="range"
            min={2}
            max={10}
            step={0.1}
            value={pitch}
            onChange={(e) => void patchPitch(Number(e.target.value), false)}
            onPointerUp={() => void patchPitch(pitch, true)}
          />
        </div>
        {(() => {
          const artwork =
            selectedFormation && selectedFormation.role !== 'launch'
              ? selectedFormation
              : project?.formations.find((f) => f.role === 'artwork')
          const budget = droneBudget(artwork, count)
          const structuralPct = (budget.structural / Math.max(budget.available, 1)) * 100
          const detailPct = (budget.detail / Math.max(budget.available, 1)) * 100
          return (
            <div className="mt-1">
              <div className="flex h-0.5 overflow-hidden bg-line">
                <div className="bg-ink" style={{ width: `${structuralPct}%` }} />
                <div className="bg-mute" style={{ width: `${detailPct}%` }} />
              </div>
              <div className="mt-1 text-[11px] text-faint">
                <span className="num text-mute">{budget.available}</span> available
                {compiling ? (
                  <span className="ml-2">Resolving trajectories</span>
                ) : (
                  <>
                    <span className="num ml-2 text-mute">{budget.structural}</span> structural
                    <span className="num ml-2 text-mute">{budget.detail}</span> detail
                  </>
                )}
              </div>
            </div>
          )
        })()}
        <QuietBtn onClick={() => void loadDemo(count)}>Load Dragon demo</QuietBtn>
      </Section>

      <Section title="Create">
        <div className="flex gap-1">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Text formation"
            className="h-6 min-w-0 flex-1 rounded-[2px] bg-raised px-1 text-[12px] text-ink"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && text.trim()) {
                void addText(text)
                setText('')
              }
            }}
          />
          <QuietBtn
            disabled={!text.trim() || compiling || converting}
            onClick={() => {
              void addText(text)
              setText('')
            }}
          >
            Add
          </QuietBtn>
        </div>
        <div className="mt-1 grid grid-cols-2">
          {PRIMS.map((p) => (
            <QuietBtn
              key={p.id}
              // Starting a second conversion would discard the one on screen
              // without saying so.
              disabled={compiling || converting}
              onClick={() => void importAsset(p.label, p.svg, 'svg')}
            >
              {p.label}
            </QuietBtn>
          ))}
        </div>
        <label className="mt-1 block cursor-pointer px-1 text-[12px] leading-6 text-mute hover:text-ink">
          Import SVG · GLB · STL
          <input
            type="file"
            accept={acceptFiles()}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) importFile(file)
              e.target.value = ''
            }}
          />
        </label>
      </Section>

      <Section title="Assets">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search"
          className="mb-1 h-6 w-full rounded-[2px] bg-raised px-1 text-[12px] text-ink"
        />
        {assets.length === 0 ? (
          <div className="px-1 py-1 text-[12px] text-faint">
            DROP A FORMATION
            <div>SVG · GLB · OBJ · STL</div>
          </div>
        ) : (
          <ul className="ui-scroll max-h-[40vh] overflow-auto">
            {assets.map((a) => {
              const on = selectedId === a.id || selectedFormation?.sourceAssetId === a.id
              return (
                <li
                  key={a.id}
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData('text/lumina-asset', a.id)}
                  className={`flex h-6 items-center gap-1 px-1 text-[12px] ${on ? 'bg-hover text-ink' : 'text-mute hover:bg-hover'}`}
                >
                  <span className="num w-7 shrink-0 text-[11px] text-faint">
                    {project?.formations.find((f) => f.sourceAssetId === a.id)?.points.length ?? a.kind}
                  </span>
                  <button
                    type="button"
                    className="min-w-0 flex-1 truncate text-left"
                    onClick={() => {
                      const f = project?.formations.find((x) => x.sourceAssetId === a.id)
                      select(f?.id ?? a.id)
                    }}
                  >
                    {a.name}
                  </button>
                  <button type="button" title="Remove" className="px-1 text-faint hover:text-hot" onClick={() => void removeAsset(a.id)}>
                    ×
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section title="Motion" open={false}>
        <div className="flex flex-wrap">
          {MOTIONS.map((m) => (
            <QuietBtn key={m.id} disabled={!selectedFormation} onClick={() => selectedFormation && addAnimation(selectedFormation.id, m.id)}>
              {m.label}
            </QuietBtn>
          ))}
        </div>
      </Section>
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
  const live = useEditor((s) => s.live)
  const selectedDrone = useEditor((s) => s.selectedDrone)
  const formation = project?.formations.find((f) => f.id === selectedId)
  const transition = project?.timeline.transitions.find((t) => t.id === selectedId)
  const animation = project?.timeline.animations.find((a) => a.id === selectedId)
  const cue = formation ? project?.timeline.cues.find((c) => c.formationId === formation.id) : undefined
  const profile = project?.droneProfile
  const swatches = formation
    ? [...new Set(formation.points.map((p) => p.color.map((c) => Math.round(c * 255)).join(',')))].slice(0, 8)
    : []
  const title = formation?.name ?? animation?.name ?? (transition ? `${transition.type}` : 'Show')

  return (
    <aside className="flex w-[240px] shrink-0 flex-col bg-chrome">
      <div className="flex h-8 items-center justify-between px-2">
        <div className="truncate text-[13px] text-ink">{title}</div>
        <div className="flex items-center gap-2">
          {violations.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[11px] text-mute">
              <StatusMark tone={violations.some((v) => v.severity === 'error') ? 'hot' : 'warn'} />
              <span className="num">{violations.length}</span>
            </span>
          )}
          {formation && (
            <div className="num text-[11px] text-faint">
              {formation.points.length} / {profile?.count ?? formation.points.length} assigned
            </div>
          )}
        </div>
      </div>
      <div className="ui-scroll min-h-0 flex-1 overflow-y-auto">
        {live.drone && selectedDrone !== null && (
          <Section title="Aircraft">
            <PropertyRow label="Id">
              <div className="num text-[12px] text-ink">{droneLabel(live.drone.id)}</div>
            </PropertyRow>
            <PropertyRow label="X" unit="m">
              <div className="num text-[12px] text-ink">{live.drone.x.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="Y" unit="m">
              <div className="num text-[12px] text-ink">{live.drone.y.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="Z" unit="m">
              <div className="num text-[12px] text-ink">{live.drone.z.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="V" unit="m/s">
              <div className="num text-[12px] text-ink">{live.drone.v.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="A" unit="m/s²">
              <div className="num text-[12px] text-ink">{live.drone.a.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="NN" unit="m">
              <div className="num text-[12px] text-ink">{live.drone.nn.toFixed(2)}</div>
            </PropertyRow>
          </Section>
        )}
        {formation && cue && (
          <Section title="Formation">
            <PropertyRow label="Name">
              <input
                className="h-6 w-full rounded-[2px] bg-raised px-1 text-[12px] text-ink"
                value={formation.name}
                onChange={(e) => renameFormation(formation.id, e.target.value)}
              />
            </PropertyRow>
            <PropertyRow label="Hold" unit="s">
              <Field type="number" value={cue.holdDuration.toFixed(1)} onChange={(v) => void patchHold(formation.id, Number(v), false)} />
            </PropertyRow>
            <div className="flex h-4 items-center">
              <input
                type="range"
                min={1}
                max={20}
                step={0.1}
                value={cue.holdDuration}
                onChange={(e) => void patchHold(formation.id, Number(e.target.value), false)}
                onPointerUp={() => void patchHold(formation.id, cue.holdDuration, true)}
              />
            </div>
            {(() => {
              const env = formationEnvelope(formation)
              const quality = project ? formationQuality(formation, project.droneProfile.count, requiredSep(project)) : null
              const nextCue = project?.timeline.cues.find((c) => c.startTime > cue.startTime)
              const nextTr = nextCue
                ? project?.timeline.transitions.find((t) => t.fromFormationId === formation.id && t.toFormationId === nextCue.formationId)
                : undefined
              const motion = nextTr && project ? transitionStats(project, nextTr) : null
              return (
                <>
                  <div className="mt-1 flex h-6 items-center gap-2 px-0">
                    <AxisGlyph />
                    <div className="num text-[11px] text-mute">
                      {env
                        ? `${env.width.toFixed(1)} × ${env.depth.toFixed(1)} × ${env.height.toFixed(1)} m`
                        : '—'}
                    </div>
                  </div>
                  {quality && (
                    <div className="mt-1 text-[11px] text-faint">
                      <div>
                        Silhouette <span className="num text-mute">{Math.round(quality.silhouette * 100)}%</span>
                      </div>
                      <div>
                        Occlusion <span className="num text-mute">{quality.occluded}</span> overlapped
                      </div>
                      <div>
                        Utilization{' '}
                        <span className="num text-mute">
                          {formation.points.length} / {project?.droneProfile.count}
                        </span>
                      </div>
                    </div>
                  )}
                  {motion && (
                    <div className="mt-1 text-[11px] text-faint">
                      <div>
                        Outer trajectory{' '}
                        <span className="num text-mute">
                          {motion.outerDeltaM >= 0 ? '+' : ''}
                          {motion.outerDeltaM.toFixed(1)} m
                        </span>
                      </div>
                      {motion.extraS > 0.05 && (
                        <div>
                          Required transition <span className="num text-mute">+{motion.extraS.toFixed(1)} s</span>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )
            })()}
            {swatches.length > 0 && (
              <div className="mt-1 flex h-6 items-center gap-1">
                {swatches.map((s) => {
                  const [r, g, b] = s.split(',').map(Number)
                  return <span key={s} className="h-2 w-2" style={{ background: `rgb(${r},${g},${b})` }} />
                })}
              </div>
            )}
          </Section>
        )}

        {animation && (
          <Section title="Motion">
            <PropertyRow label="Kind">
              <div className="text-[12px] text-ink">{animation.motion}</div>
            </PropertyRow>
            <PropertyRow label="Offset" unit="s">
              <Field type="number" value={animation.cueOffset.toFixed(1)} onChange={(v) => void patchAnimation(animation.id, { cueOffset: Number(v) }, false)} />
            </PropertyRow>
            <div className="flex h-4 items-center">
              <input
                type="range"
                min={0}
                max={12}
                step={0.1}
                value={animation.cueOffset}
                onChange={(e) => void patchAnimation(animation.id, { cueOffset: Number(e.target.value) }, false)}
                onPointerUp={() => void patchAnimation(animation.id, {}, true)}
              />
            </div>
            <PropertyRow label="Duration" unit="s">
              <Field type="number" value={animation.duration.toFixed(1)} onChange={(v) => void patchAnimation(animation.id, { duration: Number(v) }, false)} />
            </PropertyRow>
            <div className="flex h-4 items-center">
              <input
                type="range"
                min={0.5}
                max={12}
                step={0.1}
                value={animation.duration}
                onChange={(e) => void patchAnimation(animation.id, { duration: Number(e.target.value) }, false)}
                onPointerUp={() => void patchAnimation(animation.id, {}, true)}
              />
            </div>
          </Section>
        )}

        {transition && (
          <Section title="Transition">
            <PropertyRow label="Style">
              <select
                className="h-6 w-full rounded-[2px] bg-raised px-1 text-[12px] text-ink"
                value={transition.type}
                onChange={(e) => void patchTransition(transition.id, { type: e.target.value as TransitionType })}
              >
                {TRANSITIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </PropertyRow>
            <PropertyRow label="Duration" unit="s">
              <Field
                type="number"
                value={transition.duration.toFixed(1)}
                onChange={(v) => void patchTransition(transition.id, { duration: Number(v), durationMode: 'manual' }, false)}
              />
            </PropertyRow>
            <div className="flex h-4 items-center">
              <input
                type="range"
                min={1}
                max={120}
                step={0.1}
                value={Math.min(120, transition.duration)}
                onChange={(e) => void patchTransition(transition.id, { duration: Number(e.target.value), durationMode: 'manual' }, false)}
                onPointerUp={() => void patchTransition(transition.id, { durationMode: 'manual' }, true)}
              />
            </div>
            <PropertyRow label="Assign">
              <div className="num text-[12px] text-ink">
                {transition.assignment.length} / {profile?.count ?? 0}
              </div>
            </PropertyRow>
            {project &&
              (() => {
                const stats = transitionStats(project, transition)
                if (!stats) return null
                return (
                  <div className="mt-1 text-[11px] text-faint">
                    <div>
                      Distance <span className="num text-mute">{stats.meanM.toFixed(1)}</span> m mean
                    </div>
                    <div>
                      Crossings <span className="num text-mute">{stats.crossings}</span>
                    </div>
                    <div>
                      Vmax <span className="num text-mute">{stats.vmax.toFixed(2)}</span> m/s
                    </div>
                    <div>
                      Min sep <span className="num text-mute">{stats.minSep.toFixed(2)}</span> m
                    </div>
                  </div>
                )
              })()}
          </Section>
        )}

        {profile && (
          <Section title="Constraints" open={!formation && !animation && !transition}>
            <PropertyRow label="Min sep" unit="m">
              <div className="num text-[12px] text-ink">{profile.minimumSeparationM.toFixed(2)}</div>
            </PropertyRow>
            <PropertyRow label="Horiz" unit="m/s">
              <div className="num text-[12px] text-ink">{profile.maxHorizontalSpeedMps}</div>
            </PropertyRow>
            <PropertyRow label="Ascent" unit="m/s">
              <div className="num text-[12px] text-ink">{profile.maxAscentSpeedMps}</div>
            </PropertyRow>
            <PropertyRow label="Jerk" unit="m/s³">
              <div className="num text-[12px] text-ink">{profile.maxJerkMps3}</div>
            </PropertyRow>
            <PropertyRow label="GNSS">
              <div className="text-[12px] text-ink">{project?.safetyProfile.gnssMode}</div>
            </PropertyRow>
          </Section>
        )}

        <Section title="Safety" open={false}>
          <div className="mb-1 flex h-6 items-center gap-1 text-[12px] text-mute">
            <StatusMark tone={violations.some((v) => v.severity === 'error') ? 'hot' : violations.length ? 'warn' : 'ok'} />
            <span className="num">{violations.length}</span>
            <span>{violations.length === 1 ? 'marker' : 'markers'}</span>
          </div>
          {violations.length === 0 ? (
            <div className="text-[12px] text-faint">No separation events in the last compile.</div>
          ) : (
            <ul>
              {violations.slice(0, 6).map((v, i) => (
                <li key={`${v.time}-${i}`}>
                  <button type="button" onClick={() => seekViolation(v)} className="flex w-full items-baseline gap-2 py-0.5 text-left hover:bg-hover">
                    <span className={`w-0.5 self-stretch ${v.severity === 'error' ? 'bg-hot' : 'bg-warn'}`} />
                    <span className="w-8 text-[11px] text-faint">SEP</span>
                    <span className="num text-[12px] text-ink">{v.measured.toFixed(2)}</span>
                    <span className="num text-[11px] text-faint">&lt; {v.required.toFixed(2)}</span>
                    <span className="num ml-auto text-[11px] text-faint">{droneLabel(v.droneIds[0] ?? 0)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {(project?.compilerNotes ?? []).slice(0, 4).map((n, i) => (
            <div key={i} className="mt-1 text-[11px] text-mute">
              {n.message}
            </div>
          ))}
        </Section>

        {(formation || animation) && formation?.role !== 'launch' && (
          <div className="px-2 py-1">
            <button type="button" onClick={() => void removeSelected()} className="h-6 text-[12px] text-faint hover:text-hot">
              Delete selected
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
