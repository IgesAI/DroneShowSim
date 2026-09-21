'use client'

import { dynamicCapsuleRadiusM, requiredSeparationM, type Rgb, type RoleType } from '@lumina/schema'
import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import {
  createChoreographyPlayback,
  evaluateSegment,
  evaluateShow,
  isVisuallyActive,
  toThree,
  ROLE_TYPES,
  VISUAL_THRESHOLD,
  type ChoreographyFrame,
} from '@lumina/simulator'
import { useEffect, useMemo, useRef } from 'react'
import type { InstancedMesh, LineSegments as LineSegmentsType } from 'three'
import { BufferAttribute, BufferGeometry, Color, Object3D } from 'three'
import { readAssetFile } from './assets'
import { ConversionStage } from './Conversion'
import { droneLabel, nearestNeighbor, showClock } from './domain'
import { useEditor } from './store'

const srgbToLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)

function linearFromHex(hex: string): Rgb {
  const v = Number.parseInt(hex.slice(1), 16)
  return [srgbToLinear(((v >> 16) & 255) / 255), srgbToLinear(((v >> 8) & 255) / 255), srgbToLinear((v & 255) / 255)]
}

/** Engineering-view role palette. FORMATION keeps the drone's own LED colour. */
const ROLE_HEX: Record<RoleType, string> = {
  FORMATION: '#ece8e1',
  EFFECT: '#d27a3a',
  STAGING: '#6f8099',
  RESERVE: '#565b64',
  TAKEOFF: '#4e8a68',
  RTH: '#4e8a68',
}

const ROLE_LINEAR = ROLE_TYPES.map((r) => linearFromHex(ROLE_HEX[r]))
const FORMATION_CODE = ROLE_TYPES.indexOf('FORMATION')
/** Unlit drones stay on screen in engineering view, at a fraction of their role colour. */
const DARK_LEVEL = 0.3

const ROLE_LEGEND = [
  { label: 'FORMATION · LED', hex: ROLE_HEX.FORMATION },
  { label: 'EFFECT', hex: ROLE_HEX.EFFECT },
  { label: 'STAGING', hex: ROLE_HEX.STAGING },
  { label: 'TAKEOFF / RTH', hex: ROLE_HEX.TAKEOFF },
  { label: 'RESERVE', hex: ROLE_HEX.RESERVE },
]

function usePlayback() {
  const choreography = useEditor((s) => s.choreography)
  return useMemo(() => (choreography ? createChoreographyPlayback(choreography) : null), [choreography])
}

function Swarm() {
  const mesh = useRef<InstancedMesh>(null)
  const caps = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const color = useMemo(() => new Color(), [])
  const project = useEditor((s) => s.project)
  const showCapsules = useEditor((s) => s.showCapsules)
  const playback = usePlayback()
  const n = project?.droneProfile.count ?? 0
  const frame = useRef<ReturnType<typeof evaluateShow> | undefined>(undefined)
  const chFrame = useRef<ChoreographyFrame | undefined>(undefined)
  const prev = useRef(new Float32Array(0))
  const vel = useRef(new Float32Array(0))
  const lastPub = useRef(0)

  useFrame((_, dt) => {
    const state = useEditor.getState()
    if (!state.project) return
    if (state.playing) {
      const next = state.playhead + dt
      if (next >= state.project.timeline.duration) {
        if (state.loop) state.setPlayhead(0)
        else useEditor.setState({ playing: false, playhead: state.project.timeline.duration })
      } else state.setPlayhead(next)
    }
    const t = useEditor.getState().playhead
    let positions: Float32Array
    let colors: Float32Array
    let brightness: Float32Array | null = null
    let roles: Uint8Array | null = null
    if (playback) {
      const cf = playback.evaluate(t, chFrame.current)
      chFrame.current = cf
      positions = cf.positions
      colors = cf.colors
      brightness = cf.brightness
      roles = cf.roles
    } else {
      const ev = evaluateShow(state.project.formations, state.project.timeline, t, frame.current)
      frame.current = ev
      positions = ev.positions
      colors = ev.colors
    }
    const inst = mesh.current
    if (!inst) return
    const count = Math.min(n, positions.length / 3)
    const engineering = state.viewMode === 'engineering'
    const profile = state.project.droneProfile
    const safety = state.project.safetyProfile
    const capMesh = caps.current
    if (prev.current.length !== positions.length) prev.current = positions.slice()
    if (vel.current.length !== count) vel.current = new Float32Array(count)
    let airborne = 0
    let dark = 0
    for (let i = 0; i < count; i++) {
      const p: [number, number, number] = [
        positions[i * 3] ?? 0,
        positions[i * 3 + 1] ?? 0,
        positions[i * 3 + 2] ?? 0,
      ]
      const [x, y, z] = toThree(p)
      dummy.position.set(x, y, z)
      // Hiding is a scale, never a reorder: instance index stays equal to drone id.
      const lit = !brightness || isVisuallyActive(brightness[i] ?? 1)
      if (!lit) dark += 1
      dummy.scale.setScalar(lit || engineering ? (state.selectedDrone === i ? 1.45 : 1) : 0)
      dummy.updateMatrix()
      inst.setMatrixAt(i, dummy.matrix)
      let cr = colors[i * 3] ?? 1
      let cg = colors[i * 3 + 1] ?? 0.85
      let cb = colors[i * 3 + 2] ?? 0.7
      if (brightness) {
        if (engineering) {
          const role = roles?.[i] ?? FORMATION_CODE
          const swatch = role === FORMATION_CODE ? null : ROLE_LINEAR[role]
          if (swatch) {
            cr = swatch[0]
            cg = swatch[1]
            cb = swatch[2]
          }
          if (!lit) {
            cr *= DARK_LEVEL
            cg *= DARK_LEVEL
            cb *= DARK_LEVEL
          }
        } else {
          const k = brightness[i] ?? 1
          cr *= k
          cg *= k
          cb *= k
        }
      }
      color.setRGB(cr, cg, cb)
      color.convertLinearToSRGB()
      inst.setColorAt(i, color)
      const px = prev.current[i * 3] ?? p[0]
      const py = prev.current[i * 3 + 1] ?? p[1]
      const pz = prev.current[i * 3 + 2] ?? p[2]
      const speed = Math.hypot(p[0] - px, p[1] - py, p[2] - pz) / Math.max(dt, 1 / 60)
      vel.current[i] = speed
      if (p[2] >= 1) airborne += 1
      if (capMesh && state.showCapsules) {
        const r = dynamicCapsuleRadiusM(profile, safety, speed)
        dummy.scale.setScalar(Math.max(r / 0.28, 1.4))
        dummy.updateMatrix()
        capMesh.setMatrixAt(i, dummy.matrix)
      }
    }
    prev.current.set(positions)
    inst.instanceMatrix.needsUpdate = true
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true
    if (capMesh) capMesh.instanceMatrix.needsUpdate = true

    const now = performance.now()
    if (now - lastPub.current > 120) {
      lastPub.current = now
      const warnings = state.violations.filter((v) => Math.abs(v.time - t) < 0.6).length
      const id = state.selectedDrone
      let drone = null
      if (id !== null && id < count) {
        const p0 = positions[id * 3] ?? 0
        const p1 = positions[id * 3 + 1] ?? 0
        const p2 = positions[id * 3 + 2] ?? 0
        const lastV = vel.current[id] ?? 0
        const px = prev.current[id * 3] ?? p0
        const py = prev.current[id * 3 + 1] ?? p1
        const pz = prev.current[id * 3 + 2] ?? p2
        const prevSpeed = Math.hypot(p0 - px, p1 - py, p2 - pz) / Math.max(dt, 1 / 60)
        drone = {
          id,
          x: p0,
          y: p1,
          z: p2,
          v: lastV,
          a: (lastV - prevSpeed) / Math.max(dt, 1 / 60),
          nn: nearestNeighbor(positions, id),
        }
      }
      const prevLive = state.live
      if (
        prevLive.airborne !== airborne ||
        prevLive.warnings !== warnings ||
        prevLive.dark !== dark ||
        prevLive.drone?.id !== drone?.id ||
        (drone && prevLive.drone && (Math.abs(prevLive.drone.x - drone.x) > 0.02 || Math.abs(prevLive.drone.v - drone.v) > 0.05))
      ) {
        state.setLive({ airborne, warnings, dark, drone })
      }
    }
  })

  if (n <= 0) return null
  return (
    <group>
      <instancedMesh
        key={`d-${n}`}
        ref={mesh}
        args={[undefined, undefined, n]}
        // Instance matrices change every frame; the cached bounding sphere would cull the whole swarm.
        frustumCulled={false}
        onClick={(e) => {
          e.stopPropagation()
          if (e.instanceId != null) useEditor.getState().setSelectedDrone(e.instanceId)
        }}
      >
        <sphereGeometry args={[0.26, 12, 12]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      {showCapsules && (
        <instancedMesh key={`c-${n}`} ref={caps} args={[undefined, undefined, n]} frustumCulled={false}>
          <sphereGeometry args={[0.28, 8, 8]} />
          <meshBasicMaterial color="#d27a3a" transparent opacity={0.06} depthWrite={false} toneMapped={false} />
        </instancedMesh>
      )}
    </group>
  )
}

function ShowOrigin() {
  return (
    <group>
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.55, 0.75, 20]} />
        <meshBasicMaterial color="#6e6a62" transparent opacity={0.55} depthWrite={false} />
      </mesh>
    </group>
  )
}

function EditAxes() {
  const selectedId = useEditor((s) => s.selectedId)
  const selectedDrone = useEditor((s) => s.selectedDrone)
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const playback = usePlayback()
  const formation = project?.formations.find((f) => f.id === selectedId)
  const pos = useMemo(() => {
    if (selectedDrone !== null && project) {
      if (playback) return toThree(playback.positionAt(selectedDrone, playhead))
      const ev = evaluateShow(project.formations, project.timeline, playhead)
      return toThree([ev.positions[selectedDrone * 3] ?? 0, ev.positions[selectedDrone * 3 + 1] ?? 0, ev.positions[selectedDrone * 3 + 2] ?? 0])
    }
    if (!formation?.points.length) return null
    let x = 0
    let y = 0
    let z = 0
    for (const p of formation.points) {
      x += p.position[0]
      y += p.position[1]
      z += p.position[2]
    }
    const inv = 1 / formation.points.length
    return toThree([x * inv, y * inv, z * inv])
  }, [formation, playback, playhead, project, selectedDrone, selectedId])
  if (!pos || (selectedDrone === null && !formation)) return null
  return (
    <group position={pos}>
      <mesh position={[4, 0, 0]}>
        <boxGeometry args={[8, 0.05, 0.05]} />
        <meshBasicMaterial color="#c44a44" />
      </mesh>
      <mesh position={[0, 4, 0]}>
        <boxGeometry args={[0.05, 8, 0.05]} />
        <meshBasicMaterial color="#5b8def" />
      </mesh>
      <mesh position={[0, 0, 4]}>
        <boxGeometry args={[0.05, 0.05, 8]} />
        <meshBasicMaterial color="#3f9d6a" />
      </mesh>
    </group>
  )
}

function TrajectoryPaths() {
  const show = useEditor((s) => s.showTrajectories)
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const selectedDrone = useEditor((s) => s.selectedDrone)
  const line = useRef<LineSegmentsType>(null)
  const limit = project?.droneProfile.maxHorizontalSpeedMps ?? 8

  const geometry = useMemo(() => {
    const geo = new BufferGeometry()
    geo.setAttribute('position', new BufferAttribute(new Float32Array(3), 3))
    geo.setAttribute('color', new BufferAttribute(new Float32Array(3), 3))
    return geo
  }, [])

  useFrame(() => {
    if (!show || !project || !line.current) return
    const tr = project.timeline.transitions.find((t) => playhead >= t.startTime && playhead <= t.startTime + t.duration)
    if (!tr) {
      line.current.visible = false
      return
    }
    const from = project.formations.find((f) => f.id === tr.fromFormationId)
    const to = project.formations.find((f) => f.id === tr.toFormationId)
    if (!from || !to) return
    const steps = 7
    const stride = Math.max(1, Math.ceil(tr.assignment.length / 160))
    const ids = tr.assignment.map((_, i) => i).filter((i) => i % stride === 0 || i === selectedDrone)
    const segs = ids.length * steps
    const pos = new Float32Array(segs * 2 * 3)
    const col = new Float32Array(segs * 2 * 3)
    let w = 0
    for (const i of ids) {
      const asg = tr.assignment[i]
      const a = from.points[asg?.fromPointId ?? i]
      const b = to.points[asg?.toPointId ?? i]
      if (!a || !b) continue
      for (let s = 0; s < steps; s++) {
        const u0 = s / steps
        const u1 = (s + 1) / steps
        const p0 = evaluateSegment(a.position, b.position, u0, tr.type)
        const p1 = evaluateSegment(a.position, b.position, u1, tr.type)
        const t0 = toThree(p0)
        const t1 = toThree(p1)
        const speed = Math.hypot(p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]) / Math.max(tr.duration / steps, 1e-3)
        const k = Math.min(1, speed / Math.max(limit, 0.1))
        const r = 0.45 + k * 0.45
        const g = 0.55 - k * 0.35
        const bl = 0.42 - k * 0.2
        pos[w] = t0[0]
        pos[w + 1] = t0[1]
        pos[w + 2] = t0[2]
        pos[w + 3] = t1[0]
        pos[w + 4] = t1[1]
        pos[w + 5] = t1[2]
        col[w] = r
        col[w + 1] = g
        col[w + 2] = bl
        col[w + 3] = r
        col[w + 4] = g
        col[w + 5] = bl
        w += 6
      }
    }
    const attr = line.current.geometry.getAttribute('position')
    if (!attr || attr.count !== w / 3) {
      line.current.geometry.setAttribute('position', new BufferAttribute(pos.slice(0, w), 3))
      line.current.geometry.setAttribute('color', new BufferAttribute(col.slice(0, w), 3))
    } else {
      ;(attr.array as Float32Array).set(pos.subarray(0, w))
      attr.needsUpdate = true
      const cattr = line.current.geometry.getAttribute('color')
      if (cattr) {
        ;(cattr.array as Float32Array).set(col.subarray(0, w))
        cattr.needsUpdate = true
      }
    }
    line.current.visible = w > 0
  })

  if (!show) return null
  return (
    <lineSegments ref={line} geometry={geometry}>
      <lineBasicMaterial vertexColors transparent opacity={0.55} depthWrite={false} />
    </lineSegments>
  )
}

function AudienceWedge() {
  const show = useEditor((s) => s.showBounds)
  if (!show) return null
  return (
    <group position={[0, 0.03, 48]}>
      <mesh rotation={[-Math.PI / 2, 0, Math.PI]}>
        <ringGeometry args={[6, 16, 3, 1, Math.PI * 0.7, Math.PI * 0.6]} />
        <meshBasicMaterial color="#d27a3a" transparent opacity={0.22} depthWrite={false} />
      </mesh>
    </group>
  )
}

function FormationBounds() {
  const show = useEditor((s) => s.showBounds)
  const project = useEditor((s) => s.project)
  const selectedId = useEditor((s) => s.selectedId)
  const formation =
    project?.formations.find((f) => f.id === selectedId) ??
    project?.formations.find((f) => f.role !== 'launch' && f.points.length)
  const box = useMemo(() => {
    if (!formation?.points.length) return null
    let minX = Infinity
    let minY = Infinity
    let minZ = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    let maxZ = -Infinity
    for (const p of formation.points) {
      const [x, y, z] = toThree(p.position)
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      minZ = Math.min(minZ, z)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
      maxZ = Math.max(maxZ, z)
    }
    return {
      cx: (minX + maxX) / 2,
      cy: (minY + maxY) / 2,
      cz: (minZ + maxZ) / 2,
      sx: Math.max(maxX - minX, 0.4),
      sy: Math.max(maxY - minY, 0.4),
      sz: Math.max(maxZ - minZ, 0.4),
    }
  }, [formation])
  if (!show || !box) return null
  return (
    <mesh position={[box.cx, box.cy, box.cz]}>
      <boxGeometry args={[box.sx, box.sy, box.sz]} />
      <meshBasicMaterial color="#d27a3a" wireframe transparent opacity={0.45} />
    </mesh>
  )
}

function CameraRig() {
  const preset = useEditor((s) => s.cameraPreset)
  const audience = useEditor((s) => s.project?.venue.audience)
  const { camera } = useThree()
  useFrame(() => {
    if (preset === 'audience' && audience) {
      const [x, y, z] = toThree(audience.position)
      camera.position.set(x, y, z)
      const look = toThree(audience.lookAt)
      camera.lookAt(look[0], look[1], look[2])
      return
    }
    if (preset === 'top') {
      camera.position.set(0, 220, 0.2)
      camera.lookAt(0, 0, 0)
      return
    }
    if (preset === 'front') {
      camera.position.set(0, 28, 170)
      camera.lookAt(0, 18, 0)
      return
    }
    if (preset === 'side') {
      camera.position.set(170, 28, 0)
      camera.lookAt(0, 18, 0)
    }
  })
  if (preset !== 'persp') return null
  return <OrbitControls makeDefault target={[0, 18, 0]} />
}

function AudienceCompass({ headingRad }: { headingRad: number }) {
  const deg = (headingRad * 180) / Math.PI
  return (
    <div className="pointer-events-none absolute right-2 bottom-2 h-8 w-8 text-[9px] text-faint">
      <div className="relative h-8 w-8">
        <div className="absolute inset-0 rounded-full" style={{ boxShadow: 'inset 0 0 0 1px #343842' }} />
        <div className="absolute inset-0" style={{ transform: `rotate(${deg}deg)` }}>
          <div className="absolute top-0 left-1/2 h-2 w-px -translate-x-px bg-accent" />
          <div className="absolute top-2 left-1/2 -translate-x-1/2 text-[8px] tracking-wide text-mute">AUD</div>
        </div>
      </div>
    </div>
  )
}

export function Viewport() {
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const compiling = useEditor((s) => s.compiling)
  const error = useEditor((s) => s.error)
  const importAsset = useEditor((s) => s.importAsset)
  const showGrid = useEditor((s) => s.showGrid)
  const audienceView = useEditor((s) => s.audienceView)
  const live = useEditor((s) => s.live)
  const selectedDrone = useEditor((s) => s.selectedDrone)
  const choreography = useEditor((s) => s.choreography)
  const engineering = useEditor((s) => s.viewMode) === 'engineering'
  const effect = choreography?.diagnostics.effects.find(
    (e) =>
      playhead >= (e.staging?.stagingBeginsAt ?? e.effectBeginsAt) &&
      playhead <= (e.rejoin?.eventBeginsAt ?? e.effectEndsAt),
  )
  const activeCue = project?.timeline.cues.find((c) => playhead >= c.startTime && playhead < c.startTime + c.holdDuration)
  const activeTr = project?.timeline.transitions.find((tr) => playhead >= tr.startTime && playhead <= tr.startTime + tr.duration)
  const activeAnim = project?.timeline.animations.find((a) => playhead >= a.startTime && playhead <= a.startTime + a.duration)
  const label = activeAnim
    ? `${project?.formations.find((f) => f.id === activeAnim.formationId)?.name} · ${activeAnim.name}`
    : activeCue
      ? project?.formations.find((f) => f.id === activeCue.formationId)?.name
      : activeTr
        ? `${project?.formations.find((f) => f.id === activeTr.fromFormationId)?.name} → ${project?.formations.find((f) => f.id === activeTr.toFormationId)?.name}`
        : project?.name ?? 'Lumina'
  const pitch = project?.droneProfile.launchPitchM ?? 4
  const req = project ? requiredSeparationM(project.droneProfile, project.safetyProfile) : 0
  const n = project?.droneProfile.count ?? 0

  useEffect(() => {
    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      // One conversion at a time: dropping a second asset over the stage
      // would silently replace the one being tuned.
      if (useEditor.getState().conversion) return
      const file = e.dataTransfer?.files?.[0]
      if (!file) return
      void readAssetFile(file)
        .then(({ name, kind, content }) => importAsset(name, content, kind))
        .catch((err) => useEditor.setState({ error: err instanceof Error ? err.message : 'Import failed' }))
    }
    const prevent = (e: DragEvent) => e.preventDefault()
    window.addEventListener('dragover', prevent)
    window.addEventListener('drop', onDrop)
    return () => {
      window.removeEventListener('dragover', prevent)
      window.removeEventListener('drop', onDrop)
    }
  }, [importAsset])

  return (
    <div className="relative min-h-0 flex-1 bg-canvas">
      <Canvas camera={{ position: [0, 38, 160], fov: 38 }} dpr={[1, 1.75]}>
        <color attach="background" args={['#0b0c0f']} />
        <fog attach="fog" args={['#0b0c0f', 120, 520]} />
        <hemisphereLight args={['#6b675f', '#16181c', 0.35]} />
        <Swarm />
        <ShowOrigin />
        <EditAxes />
        <TrajectoryPaths />
        <AudienceWedge />
        <FormationBounds />
        {showGrid && (
          <Grid
            args={[400, 400]}
            cellSize={5}
            cellColor="#252830"
            sectionSize={25}
            sectionColor="#3a3f49"
            fadeDistance={340}
            infiniteGrid
          />
        )}
        <CameraRig />
      </Canvas>
      {!project && (
        <div className="absolute inset-0 z-10 grid place-items-center bg-canvas/70 px-6">
          <div className="max-w-sm text-left">
            <div className="text-[16px] tracking-wide text-ink">{compiling ? 'RESOLVING TRAJECTORIES' : 'DROP A FORMATION'}</div>
            <p className="mt-2 text-[13px] leading-relaxed text-mute">
              {compiling ? `dshowc is assigning ${n || 80} drones to the launch grid.` : 'SVG · GLB · OBJ · STL'}
            </p>
          </div>
        </div>
      )}
      {project && (
        <div className="pointer-events-none absolute top-2 left-2 text-[11px] text-mute">
          <div>
            <span className="text-ink">{label}</span>
            <span className="num ml-2">
              {n} drones · sep ≥ {req.toFixed(2)} m · pad {pitch.toFixed(1)}
              {compiling ? ' · resolving trajectories' : ''}
            </span>
          </div>
          {live.drone && selectedDrone !== null && (
            <div className="num mt-1 text-ink">
              {droneLabel(live.drone.id)} · X {live.drone.x.toFixed(2)} · Y {live.drone.y.toFixed(2)} · Z {live.drone.z.toFixed(2)} · V{' '}
              {live.drone.v.toFixed(2)} · NN {live.drone.nn.toFixed(2)}
            </div>
          )}
        </div>
      )}
      {project && (
        <div className="pointer-events-none absolute top-2 right-2 text-right text-[11px] text-mute">
          {audienceView && <div className="mb-1 tracking-wide text-faint">AUDIENCE VIEW</div>}
          {engineering && <div className="mb-1 tracking-wide text-accent">ENGINEERING VIEW</div>}
          <div className="num text-ink">{showClock(playhead)}</div>
          <div>
            <span className="num">{live.airborne}</span> airborne
          </div>
          {choreography && (
            <div>
              <span className="num">{live.dark}</span> dark
            </div>
          )}
          <div>
            <span className="num">{live.warnings}</span> {live.warnings === 1 ? 'warning' : 'warnings'}
          </div>
        </div>
      )}
      {project && engineering && (
        <div className="pointer-events-none absolute bottom-2 left-2 text-[11px] text-mute">
          {effect && (
            <div className="num mb-1 text-ink">
              {effect.effectName} · {effect.allocation.allocatedDroneCount}/{effect.allocation.requestedDroneCount} allocated ·{' '}
              {effect.darkTravelDuration.toFixed(1)} s dark travel
            </div>
          )}
          {ROLE_LEGEND.map((row) => (
            <div key={row.label} className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5" style={{ background: row.hex }} />
              {row.label}
            </div>
          ))}
          <div className="mt-1 text-faint">dim · brightness ≤ {VISUAL_THRESHOLD}</div>
        </div>
      )}
      {project && <AudienceCompass headingRad={project.venue.showHeadingRad} />}
      {error && <div className="absolute left-2 top-8 max-w-md text-[12px] text-hot">{error}</div>}
      <ConversionStage />
    </div>
  )
}
