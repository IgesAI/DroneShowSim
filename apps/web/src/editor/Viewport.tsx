'use client'

import { capsuleRadiusM, dynamicCapsuleRadiusM, requiredSeparationM } from '@lumina/schema'
import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { evaluateShow, toThree } from '@lumina/simulator'
import { useEffect, useMemo, useRef } from 'react'
import type { InstancedMesh } from 'three'
import { Color, Object3D } from 'three'
import { acceptFiles, readAssetFile } from './assets'
import { useEditor } from './store'

function Swarm() {
  const mesh = useRef<InstancedMesh>(null)
  const caps = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const color = useMemo(() => new Color(), [])
  const project = useEditor((s) => s.project)
  const showCapsules = useEditor((s) => s.showCapsules)
  const n = project?.droneProfile.count ?? 0
  const frame = useRef({ positions: new Float32Array(0), colors: new Float32Array(0), label: '—' })
  const prev = useRef(new Float32Array(0))

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
    const ev = evaluateShow(state.project.formations, state.project.timeline, useEditor.getState().playhead, frame.current)
    frame.current = ev
    const inst = mesh.current
    if (!inst) return
    const count = Math.min(n, ev.positions.length / 3)
    const profile = state.project.droneProfile
    const safety = state.project.safetyProfile
    const capMesh = caps.current
    if (prev.current.length !== ev.positions.length) prev.current = ev.positions.slice()
    for (let i = 0; i < count; i++) {
      const p: [number, number, number] = [
        ev.positions[i * 3] ?? 0,
        ev.positions[i * 3 + 1] ?? 0,
        ev.positions[i * 3 + 2] ?? 0,
      ]
      const [x, y, z] = toThree(p)
      dummy.position.set(x, y, z)
      dummy.scale.setScalar(1)
      dummy.updateMatrix()
      inst.setMatrixAt(i, dummy.matrix)
      color.setRGB(ev.colors[i * 3] ?? 1, ev.colors[i * 3 + 1] ?? 0.85, ev.colors[i * 3 + 2] ?? 0.7)
      color.convertLinearToSRGB()
      inst.setColorAt(i, color)
      if (capMesh && state.showCapsules) {
        const px = prev.current[i * 3] ?? p[0]
        const py = prev.current[i * 3 + 1] ?? p[1]
        const pz = prev.current[i * 3 + 2] ?? p[2]
        const speed = Math.hypot(p[0] - px, p[1] - py, p[2] - pz) / Math.max(dt, 1 / 60)
        const r = dynamicCapsuleRadiusM(profile, safety, speed)
        dummy.scale.setScalar(Math.max(r / 0.28, 1.4))
        dummy.updateMatrix()
        capMesh.setMatrixAt(i, dummy.matrix)
      }
    }
    prev.current.set(ev.positions)
    inst.instanceMatrix.needsUpdate = true
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true
    if (capMesh) capMesh.instanceMatrix.needsUpdate = true
  })

  if (n <= 0) return null
  return (
    <group>
      <instancedMesh key={`d-${n}`} ref={mesh} args={[undefined, undefined, n]}>
        <sphereGeometry args={[0.26, 16, 16]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      {showCapsules && (
        <instancedMesh key={`c-${n}`} ref={caps} args={[undefined, undefined, n]}>
          <sphereGeometry args={[0.28, 10, 10]} />
          <meshBasicMaterial color="#818cf8" transparent opacity={0.07} depthWrite={false} toneMapped={false} />
        </instancedMesh>
      )}
    </group>
  )
}

function ScaleBar() {
  return (
    <group position={[0, 0.04, 0]}>
      <mesh position={[5, 0, 0]}>
        <boxGeometry args={[10, 0.06, 0.12]} />
        <meshBasicMaterial color="#6366f1" />
      </mesh>
      {[0, 5, 10].map((m) => (
        <mesh key={m} position={[m, 0.12, 0]}>
          <boxGeometry args={[0.08, 0.28, 0.08]} />
          <meshBasicMaterial color="#a5b4fc" />
        </mesh>
      ))}
    </group>
  )
}

function AudienceRig() {
  const audienceView = useEditor((s) => s.audienceView)
  const audience = useEditor((s) => s.project?.venue.audience)
  const { camera } = useThree()
  useFrame(() => {
    if (!audienceView || !audience) return
    const [x, y, z] = toThree(audience.position)
    camera.position.set(x, y, z)
    const look = toThree(audience.lookAt)
    camera.lookAt(look[0], look[1], look[2])
  })
  if (audienceView) return null
  return <OrbitControls makeDefault target={[0, 18, 0]} />
}

export function Viewport() {
  const project = useEditor((s) => s.project)
  const playhead = useEditor((s) => s.playhead)
  const compiling = useEditor((s) => s.compiling)
  const error = useEditor((s) => s.error)
  const importAsset = useEditor((s) => s.importAsset)
  const audienceView = useEditor((s) => s.audienceView)
  const setAudienceView = useEditor((s) => s.setAudienceView)
  const showCapsules = useEditor((s) => s.showCapsules)
  const setShowCapsules = useEditor((s) => s.setShowCapsules)
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
  const phase = activeCue?.phase ?? (activeTr ? 'show' : 'show')
  const pitch = project?.droneProfile.launchPitchM ?? 4
  const capsule = project ? capsuleRadiusM(project.droneProfile, project.safetyProfile) : 0
  const req = project ? requiredSeparationM(project.droneProfile, project.safetyProfile) : 0

  useEffect(() => {
    const onDrop = (e: DragEvent) => {
      e.preventDefault()
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
    <div className="relative min-h-0 flex-1 bg-[#0b1220]">
      <Canvas camera={{ position: [0, 38, 160], fov: 38 }} dpr={[1, 1.75]}>
        <color attach="background" args={['#0b1220']} />
        <fog attach="fog" args={['#0b1220', 90, 480]} />
        <hemisphereLight args={['#a5b4fc', '#1e1b4b', 0.4]} />
        <Swarm />
        <ScaleBar />
        <Grid args={[400, 400]} cellSize={5} cellColor="#1e293b" sectionSize={25} sectionColor="#312e81" fadeDistance={320} infiniteGrid />
        <AudienceRig />
      </Canvas>
      {!project && (
        <div className="absolute inset-0 z-10 grid place-items-center bg-[#0b1220]/70 px-6 text-center">
          <div className="max-w-sm">
            <div className="font-[family-name:var(--font-display)] text-lg text-white">
              {compiling ? 'dshowc is compiling…' : 'No show loaded'}
            </div>
            <p className="mt-2 text-sm text-gray-400">
              {compiling
                ? 'Launch grid and formations appear when the compiler finishes. First load uses 80 drones so you see the grid sooner.'
                : 'Load the Cobra demo, or upload SVG / GLB / OBJ / STL. If this stays empty, start dshowc on port 8000.'}
            </p>
            <label className="mt-4 inline-block cursor-pointer rounded-full bg-indigo-600 px-4 py-2 text-sm text-white">
              Upload formation
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
          </div>
        </div>
      )}
      <div className="pointer-events-none absolute left-4 top-4">
        <div className="text-[11px] uppercase tracking-wide text-gray-400">
          {audienceView ? 'Audience view · locked' : 'Viewport · DSHOW_LOCAL_RH'} · {phase}
        </div>
        <div className="font-[family-name:var(--font-display)] text-lg font-semibold text-white">{label}</div>
        <div className="text-xs text-gray-400">
          {project?.droneProfile.count ?? 0} drones · pad {pitch.toFixed(1)} m · capsule {capsule.toFixed(2)} m · sep ≥ {req.toFixed(2)} m
          {compiling ? ' · compiling' : ''}
        </div>
        <div className="mt-1 text-[11px] text-indigo-300">10 m scale on ground · {project?.venue.altitudeDatum ?? 'local-z'} · {project?.clockDomain ?? 'show-monotonic'}</div>
        {error && <div className="mt-2 max-w-md text-xs text-rose-400">{error}</div>}
      </div>
      <div className="absolute right-4 top-4 flex flex-col gap-2">
        <button type="button" onClick={() => setShowCapsules(!showCapsules)} className={`rounded-full border px-3 py-1.5 text-[11px] ${showCapsules ? 'border-indigo-400/50 text-indigo-200' : 'border-white/10 text-gray-400'}`}>
          Capsules
        </button>
        <button type="button" onClick={() => setAudienceView(!audienceView)} className={`rounded-full border px-3 py-1.5 text-[11px] ${audienceView ? 'border-indigo-400/50 text-indigo-200' : 'border-white/10 text-gray-400'}`}>
          Audience
        </button>
        <div className="rounded-full border border-white/10 px-3 py-1.5 text-[11px] text-gray-400">{project?.showState ?? 'UNCOMPILED'}</div>
      </div>
    </div>
  )
}
