'use client'

import type { Formation, SamplingMode } from '@lumina/schema'
import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { toThree } from '@lumina/simulator'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { InstancedMesh } from 'three'
import { Color, EdgesGeometry, Object3D, PlaneGeometry, Vector3 } from 'three'
import { isMesh } from './assets'
import { useEditor, type ConversionSettings } from './store'

/**
 * Points the packer could not seat on the artwork. They are real aircraft in
 * real airspace that are not drawing anything, so they get their own colour
 * rather than being buried in a count.
 */
const OFF_SHAPE = new Set(['halo', 'spark', 'fallback'])
/** Matches the backend's structural/detail split. */
const STRUCTURAL = 0.61

const MESH_MODES: { id: SamplingMode; label: string }[] = [
  { id: 'surface', label: 'Surface' },
  { id: 'silhouette', label: 'Silhouette' },
  { id: 'wireframe', label: 'Wireframe' },
]

function pointRole(importance: number, featureType?: string | null) {
  if (featureType && OFF_SHAPE.has(featureType)) return 'off' as const
  return importance >= STRUCTURAL ? ('structural' as const) : ('detail' as const)
}

function DraftSwarm({ formation }: { formation: Formation }) {
  const mesh = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const color = useMemo(() => new Color(), [])
  const n = formation.points.length

  useEffect(() => {
    const inst = mesh.current
    if (!inst) return
    for (let i = 0; i < n; i++) {
      const p = formation.points[i]
      if (!p) continue
      const [x, y, z] = toThree(p.position)
      dummy.position.set(x, y, z)
      dummy.scale.setScalar(1)
      dummy.updateMatrix()
      inst.setMatrixAt(i, dummy.matrix)
      const role = pointRole(p.importance, p.featureType)
      if (role === 'off') color.setRGB(0.76, 0.29, 0.27)
      else if (role === 'structural') color.setRGB(p.color[0], p.color[1], p.color[2]).convertLinearToSRGB()
      else {
        color.setRGB(p.color[0] * 0.4, p.color[1] * 0.4, p.color[2] * 0.4).convertLinearToSRGB()
      }
      inst.setColorAt(i, color)
    }
    inst.instanceMatrix.needsUpdate = true
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true
  }, [color, dummy, formation, n])

  if (n <= 0) return null
  return (
    <instancedMesh key={`draft-${n}`} ref={mesh} args={[undefined, undefined, n]} frustumCulled={false}>
      <sphereGeometry args={[0.32, 10, 10]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}

/**
 * Keep the figure in frame as it is retuned.
 *
 * Resizing the artwork changes the figure by a factor of several, so a fixed
 * camera turns "look at what this becomes" into a row of dots off the edge
 * of the screen. Only the distance and the target move: the direction the
 * operator is looking from is theirs to keep.
 */
function FitCamera({ formation }: { formation: Formation | null }) {
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as { target: Vector3; update: () => void } | null
  const fitted = useRef(0)

  useEffect(() => {
    const pts = formation?.points
    if (!pts?.length) return
    const lo = new Vector3(Infinity, Infinity, Infinity)
    const hi = new Vector3(-Infinity, -Infinity, -Infinity)
    const p = new Vector3()
    for (const point of pts) {
      const [x, y, z] = toThree(point.position)
      p.set(x, y, z)
      lo.min(p)
      hi.max(p)
    }
    const centre = lo.clone().add(hi).multiplyScalar(0.5)
    const radius = Math.max(hi.distanceTo(lo) * 0.5, 1)
    // Ignore the small changes a seed or a nudge produces, so the view only
    // moves when the figure genuinely did.
    if (Math.abs(radius - fitted.current) <= fitted.current * 0.15) return
    fitted.current = radius

    const fov = 'fov' in camera ? (camera.fov as number) : 40
    const dist = (radius / Math.tan((fov * Math.PI) / 360)) * 1.3
    const target = controls?.target ?? new Vector3(0, 24, 0)
    const dir = camera.position.clone().sub(target)
    if (dir.lengthSq() < 1e-6) dir.set(0, 0.25, 1)
    camera.position.copy(centre).add(dir.normalize().multiplyScalar(dist))
    camera.lookAt(centre)
    if (controls) {
      controls.target.copy(centre)
      controls.update()
    }
  }, [camera, controls, formation])

  return null
}

/**
 * The cleared ceiling, drawn only once the figure is tall enough to care.
 *
 * Drawn as an outline rather than a translucent sheet: the operator is
 * usually looking at the figure from roughly its own height, and a
 * horizontal plane seen edge-on from there is invisible exactly when it
 * matters most.
 */
function Clearance({ ceilingM, topM, spanM }: { ceilingM: number; topM: number; spanM: number }) {
  const side = Math.max(spanM * 1.5, 60)
  // A plane's edges are its four borders: the shared diagonal is coplanar and
  // drops out, which a wireframe box would have drawn across the sky.
  const border = useMemo(() => new EdgesGeometry(new PlaneGeometry(side, side)), [side])
  useEffect(() => () => border.dispose(), [border])
  if (topM < ceilingM * 0.8) return null
  const over = topM > ceilingM
  const hex = over ? '#c44a44' : '#d59a2a'
  return (
    <group position={[0, ceilingM, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <lineSegments geometry={border}>
        <lineBasicMaterial color={hex} transparent opacity={0.75} />
      </lineSegments>
      <mesh>
        <planeGeometry args={[side, side]} />
        <meshBasicMaterial color={hex} transparent opacity={over ? 0.14 : 0.06} depthWrite={false} />
      </mesh>
    </group>
  )
}

function Metric({
  label,
  value,
  unit,
  tone = 'ink',
}: {
  label: string
  value: string
  unit?: string
  tone?: 'ink' | 'ok' | 'warn' | 'hot'
}) {
  const color = tone === 'ok' ? 'text-ok' : tone === 'warn' ? 'text-warn' : tone === 'hot' ? 'text-hot' : 'text-ink'
  return (
    <div className="flex items-baseline justify-between gap-2 py-[3px]">
      <span className="text-[12px] text-mute">{label}</span>
      <span className={`num text-[12px] ${color}`}>
        {value}
        {unit ? <span className="ml-1 text-faint">{unit}</span> : null}
      </span>
    </div>
  )
}

function Slider({
  label,
  unit,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string
  unit: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between">
        <span className="text-[12px] text-mute">{label}</span>
        <span className="num text-[12px] text-ink">
          {value.toFixed(step < 1 ? 1 : 0)}
          <span className="ml-1 text-faint">{unit}</span>
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1"
      />
    </div>
  )
}

export function ConversionStage() {
  const conversion = useEditor((s) => s.conversion)
  const project = useEditor((s) => s.project)
  const retune = useEditor((s) => s.retuneConversion)
  const commit = useEditor((s) => s.commitConversion)
  const cancel = useEditor((s) => s.cancelConversion)
  const [draft, setDraft] = useState<ConversionSettings | null>(null)

  // Follow the store when a new asset arrives, but let the sliders own the
  // value while the operator is dragging one.
  const assetId = conversion?.assetId
  useEffect(() => {
    setDraft(conversion ? conversion.settings : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId])

  // Regenerating on every pointer event would queue a request per pixel.
  useEffect(() => {
    if (!draft || !conversion) return
    const settings = conversion.settings
    if (
      draft.widthM === settings.widthM &&
      draft.heightM === settings.heightM &&
      draft.depthM === settings.depthM &&
      draft.seed === settings.seed &&
      draft.mode === settings.mode
    ) {
      return
    }
    const id = setTimeout(() => void retune(draft), 180)
    return () => clearTimeout(id)
  }, [draft, conversion, retune])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Escape') {
        e.preventDefault()
        useEditor.getState().cancelConversion()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  if (!conversion || !draft || !project) return null

  const { formation, report, generating, error } = conversion
  const mesh = isMesh(conversion.kind)
  const fleet = project.droneProfile.count
  const ceiling = project.venue.maxAltitudeM
  const placed = report?.pointCount ?? 0
  const offShape = report?.overflowCount ?? 0
  const authored = report?.authoredImportance ?? false
  const structural = report?.structuralCount ?? 0
  const detail = Math.max(0, (report?.detailCount ?? 0) - offShape)
  const onShape = Math.max(0, placed - offShape)
  const pct = (k: number) => `${(k / Math.max(placed, 1)) * 100}%`
  // A figure that breaches the separation floor produces violations the
  // moment it is compiled, so the gate is the place to stop it.
  const flyable = report ? report.safeSeparation : true
  const ready = Boolean(formation) && !generating && flyable

  return (
    <div className="absolute inset-0 z-20 flex bg-canvas">
      <div className="relative min-w-0 flex-1">
        <Canvas camera={{ position: [0, 40, 150], fov: 40 }} dpr={[1, 1.75]}>
          <color attach="background" args={['#0b0c0f']} />
          <hemisphereLight args={['#6b675f', '#16181c', 0.35]} />
          {formation && <DraftSwarm formation={formation} />}
          {report && (
            <Clearance
              ceilingM={ceiling}
              topM={report.highestZ}
              spanM={Math.max(report.widthM, report.depthM)}
            />
          )}
          <Grid
            args={[400, 400]}
            cellSize={5}
            cellColor="#252830"
            sectionSize={25}
            sectionColor="#3a3f49"
            fadeDistance={340}
            infiniteGrid
          />
          <OrbitControls makeDefault target={[0, 24, 0]} />
          <FitCamera formation={formation} />
        </Canvas>

        <div className="pointer-events-none absolute top-2 left-2 text-[11px]">
          <div className="tracking-wide text-accent">CONVERT TO DRONES</div>
          <div className="mt-0.5 text-[13px] text-ink">{conversion.name}</div>
          <div className="num mt-0.5 text-mute">
            {conversion.kind.toUpperCase()} · {generating ? 'sampling' : `${placed} / ${fleet} drones placed`}
          </div>
        </div>

        <div className="pointer-events-none absolute bottom-2 left-2 text-[11px] text-mute">
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 bg-ink" /> holds the shape
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5" style={{ background: '#5c5a55' }} /> fills it in
          </div>
          {offShape > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 bg-hot" /> not on the shape
            </div>
          )}
        </div>
      </div>

      <div className="w-px bg-line-strong" />

      <div className="ui-scroll flex w-[268px] shrink-0 flex-col overflow-y-auto bg-panel">
        <div className="px-3 pt-3 pb-2">
          <div className="text-[11px] tracking-wide text-faint">DRONE BUDGET</div>
          <div className="mt-2 flex h-1 overflow-hidden bg-line">
            {authored ? (
              <>
                <div className="bg-ink" style={{ width: pct(structural) }} />
                <div style={{ width: pct(detail), background: '#5c5a55' }} />
              </>
            ) : (
              <div className="bg-ink" style={{ width: pct(onShape) }} />
            )}
            <div className="bg-hot" style={{ width: pct(offShape) }} />
          </div>
          <div className="num mt-1.5 text-[11px] text-faint">
            {authored ? (
              <>
                <span className="text-mute">{structural}</span> structural
                <span className="ml-2 text-mute">{detail}</span> detail
              </>
            ) : (
              <>
                <span className="text-mute">{onShape}</span> on the shape
              </>
            )}
            {offShape > 0 && <span className="ml-2 text-hot">{offShape} off-shape</span>}
          </div>
          {report && !authored && (
            // Without this the split reads "0 structural", which sounds like
            // a fault in the artwork rather than an absence of authoring.
            <div className="mt-1 text-[11px] leading-relaxed text-faint">
              Every point counts the same here. Tag features with{' '}
              <span className="num">data-importance</span> in the SVG to protect the ones effects must not
              borrow.
            </div>
          )}
        </div>

        <div className="h-px bg-line" />

        <div className="px-3 py-2">
          <div className="text-[11px] tracking-wide text-faint">GEOMETRY</div>
          <Slider
            label="Width"
            unit="m"
            min={10}
            max={320}
            step={1}
            value={draft.widthM}
            onChange={(widthM) => setDraft({ ...draft, widthM })}
          />
          <Slider
            label="Height"
            unit="m"
            min={5}
            max={Math.max(40, Math.round(ceiling))}
            step={1}
            value={draft.heightM}
            onChange={(heightM) => setDraft({ ...draft, heightM })}
          />
          {mesh && (
            <Slider
              label="Depth"
              unit="m"
              min={0}
              max={200}
              step={1}
              value={draft.depthM}
              onChange={(depthM) => setDraft({ ...draft, depthM })}
            />
          )}
          <Slider
            label="Seed"
            unit=""
            min={1}
            max={64}
            step={1}
            value={draft.seed}
            onChange={(seed) => setDraft({ ...draft, seed })}
          />
          {mesh ? (
            <div className="mt-2">
              <div className="text-[12px] text-mute">Sampling</div>
              <div className="mt-1 grid grid-cols-3 gap-1">
                {MESH_MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setDraft({ ...draft, mode: m.id })}
                    className={`h-6 rounded-[2px] text-[11px] ${
                      draft.mode === m.id ? 'bg-hover text-ink' : 'bg-raised text-mute hover:bg-hover hover:text-ink'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            // Vector artwork is sampled along its strokes, so the mesh modes
            // would be a control that does nothing.
            <div className="mt-2 text-[11px] text-faint">Vector artwork is sampled along its strokes.</div>
          )}
        </div>

        <div className="h-px bg-line" />

        <div className="px-3 py-2">
          <div className="text-[11px] tracking-wide text-faint">AS FLOWN</div>
          {report ? (
            <>
              <Metric
                label="Nearest neighbour"
                value={report.minSeparationM.toFixed(2)}
                unit="m"
                tone={!report.safeSeparation ? 'hot' : report.spacingOk ? 'ok' : 'warn'}
              />
              <Metric label="Needed for the morph" value={report.requiredSeparationM.toFixed(2)} unit="m" />
              <Metric label="Never breach" value={report.hardMinimumM.toFixed(2)} unit="m" />
              <Metric
                label="Figure"
                value={`${report.widthM.toFixed(0)} × ${report.heightM.toFixed(0)}`}
                unit="m"
              />
              <Metric
                label="Top of figure"
                value={report.highestZ.toFixed(0)}
                unit={`m of ${ceiling.toFixed(0)}`}
                tone={report.fitsAirspace ? 'ink' : 'hot'}
              />
              <Metric
                label="Packer growth"
                value={`${report.packScale.toFixed(2)}×`}
                tone={report.packScale > 1.25 ? 'warn' : 'ink'}
              />
            </>
          ) : (
            <div className="py-2 text-[12px] text-faint">{generating ? 'Sampling…' : '—'}</div>
          )}
        </div>

        {(report?.notes.length || error) && (
          <>
            <div className="h-px bg-line" />
            <div className="px-3 py-2">
              {error && <div className="text-[12px] leading-relaxed text-hot">{error}</div>}
              {report?.notes.map((note) => (
                <div key={note} className="mb-1.5 text-[11px] leading-relaxed text-warn last:mb-0">
                  {note}
                </div>
              ))}
            </div>
          </>
        )}

        <div className="mt-auto">
          <div className="h-px bg-line" />
          <div className="px-3 py-2">
            <div className="text-[11px] leading-relaxed text-faint">
              Fleet is {fleet} drones. Every formation uses the whole fleet, so change the count in the show panel,
              not here.
            </div>
            <div className="mt-2 flex gap-1">
              <button
                type="button"
                onClick={cancel}
                className="h-7 flex-1 rounded-[2px] bg-raised text-[12px] text-mute hover:bg-hover hover:text-ink"
              >
                Discard
              </button>
              <button
                type="button"
                disabled={!ready}
                onClick={() => void commit()}
                className="h-7 flex-[1.4] rounded-[2px] bg-accent text-[12px] text-canvas hover:bg-accent-hover disabled:opacity-35"
              >
                {generating ? 'Sampling…' : flyable ? 'Add to show' : 'Too tight to fly'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
