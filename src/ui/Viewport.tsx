import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import type { InstancedMesh } from 'three'
import { Color, Object3D } from 'three'
import { tickPlayback, useShow } from '../store'

function Swarm() {
  const mesh = useRef<InstancedMesh>(null)
  const dummy = useMemo(() => new Object3D(), [])
  const color = useMemo(() => new Color(), [])
  const n = useShow((s) => s.settings.droneCount)

  useFrame((_, dt) => {
    tickPlayback(dt)
    const { pos, col } = useShow.getState()
    const inst = mesh.current
    if (!inst) return
    const count = Math.min(n, pos.length / 3)
    for (let i = 0; i < count; i++) {
      dummy.position.set(pos[i * 3] ?? 0, pos[i * 3 + 1] ?? 0, pos[i * 3 + 2] ?? 0)
      dummy.scale.setScalar(1)
      dummy.updateMatrix()
      inst.setMatrixAt(i, dummy.matrix)
      color.setRGB(col[i * 3] ?? 1, col[i * 3 + 1] ?? 0.85, col[i * 3 + 2] ?? 0.7)
      inst.setColorAt(i, color)
    }
    inst.instanceMatrix.needsUpdate = true
    if (inst.instanceColor) inst.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, n]}>
      <sphereGeometry args={[1.15, 8, 8]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}

function VolumeBox() {
  const w = useShow((s) => s.settings.width)
  const h = useShow((s) => s.settings.height)
  const d = useShow((s) => s.settings.depth)
  return (
    <mesh position={[0, 8 + h / 2, 0]}>
      <boxGeometry args={[w, h, d]} />
      <meshBasicMaterial color="#7cffb2" wireframe transparent opacity={0.08} />
    </mesh>
  )
}

function Audience() {
  return (
    <group position={[0, 0, 92]}>
      {[-30, -15, 0, 15, 30].map((x) => (
        <mesh key={x} position={[x, 1.1, 0]}>
          <capsuleGeometry args={[0.45, 1.1, 4, 8]} />
          <meshStandardMaterial color="#3a414b" />
        </mesh>
      ))}
    </group>
  )
}

export function Viewport() {
  const dropActive = useShow((s) => s.dropActive)
  const compiling = useShow((s) => s.compiling)
  const label = useShow((s) => s.label)
  const n = useShow((s) => s.settings.droneCount)
  const importFiles = useShow((s) => s.importFiles)
  const setDropActive = useShow((s) => s.setDropActive)

  useEffect(() => {
    const onDrag = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes('Files')) return
      e.preventDefault()
      setDropActive(true)
    }
    const onLeave = (e: DragEvent) => {
      e.preventDefault()
      if (e.relatedTarget) return
      setDropActive(false)
    }
    const onDrop = (e: DragEvent) => {
      e.preventDefault()
      setDropActive(false)
      const files = [...(e.dataTransfer?.files ?? [])]
      void importFiles(files)
    }
    window.addEventListener('dragover', onDrag)
    window.addEventListener('dragleave', onLeave)
    window.addEventListener('drop', onDrop)
    return () => {
      window.removeEventListener('dragover', onDrag)
      window.removeEventListener('dragleave', onLeave)
      window.removeEventListener('drop', onDrop)
    }
  }, [importFiles, setDropActive])

  return (
    <div className="relative min-h-0 flex-1 bg-black">
      <Canvas camera={{ position: [0, 48, 210], fov: 38 }} dpr={[1, 1.75]}>
        <color attach="background" args={['#07090b']} />
        <fog attach="fog" args={['#07090b', 80, 420]} />
        <hemisphereLight args={['#9eb6ff', '#1a120c', 0.35]} />
        <ambientLight intensity={0.15} />
        <Swarm />
        <VolumeBox />
        <Audience />
        <Grid
          args={[400, 400]}
          cellSize={5}
          cellColor="#1b2028"
          sectionSize={25}
          sectionColor="#2a3340"
          fadeDistance={280}
          infiniteGrid
        />
        <OrbitControls enablePan makeDefault target={[0, 48, 0]} />
      </Canvas>
      <div className="pointer-events-none absolute left-4 top-4 flex flex-col gap-1">
        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-mute">View</div>
        <div className="text-lg font-medium">{label}</div>
        <div className="font-mono text-xs text-mute">{n} drones{compiling ? ' · compiling' : ''}</div>
      </div>
      {dropActive && (
        <div className="absolute inset-3 z-10 grid place-items-center rounded-xl border border-dashed border-ok/60 bg-ink/70">
          <div className="text-center">
            <div className="text-lg font-medium text-ok">Drop SVG, PNG, JPG, GLB, OBJ, STL</div>
            <div className="mt-1 text-sm text-mute">The compiler will allocate drones and insert a clip</div>
          </div>
        </div>
      )}
    </div>
  )
}
