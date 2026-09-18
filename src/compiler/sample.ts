import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import type { BufferGeometry, Mesh } from 'three'
import { farthestPointSample, fitToVolume, hexToColor, separatePoints, weightedPick } from './math'
import { samplePreset } from './presets'
import { ClipKind, type Clip, type Color, type Vec3, type Volume } from './types'

function hex(color: string): Color {
  return hexToColor(color)
}

function sampleCanvas(
  canvas: HTMLCanvasElement,
  n: number,
  volume: Volume,
  invert = true,
): Vec3[] {
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return []
  const { width, height } = canvas
  const img = ctx.getImageData(0, 0, width, height)
  const data = img.data
  const candidates: Vec3[] = []
  const weights: number[] = []

  const lumAt = (x: number, y: number) => {
    const i = (y * width + x) * 4
    return (data[i]! + data[i + 1]! + data[i + 2]!) / 3
  }

  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const lum = lumAt(x, y)
      const ink = invert ? 255 - lum : lum
      if (ink < 12) continue
      const gx = lumAt(x + 1, y) - lumAt(x - 1, y)
      const gy = lumAt(x, y + 1) - lumAt(x, y - 1)
      const edge = Math.hypot(gx, gy)
      const importance = ink / 255 + edge / 80
      if (importance < 0.08 && Math.random() > importance * 2) continue
      candidates.push({
        x: (x / width - 0.5) * 2,
        y: (0.5 - y / height) * (height / width) * 2,
        z: 0,
      })
      weights.push(importance * (0.35 + edge / 60))
    }
  }
  const picked = weights.length ? weightedPick(candidates, weights, n) : farthestPointSample(candidates, n)
  return fitToVolume(picked, volume, true)
}

export async function sampleText(text: string, n: number, volume: Volume): Promise<Vec3[]> {
  if (document.fonts?.ready) await document.fonts.ready
  const canvas = document.createElement('canvas')
  canvas.width = 1600
  canvas.height = 480
  const ctx = canvas.getContext('2d')
  if (!ctx) return []
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#000000'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  let size = 260
  const family = '800 Arial, "IBM Plex Sans", system-ui, sans-serif'
  ctx.font = `${size}px ${family}`
  while (ctx.measureText(text).width > canvas.width * 0.88 && size > 48) {
    size -= 8
    ctx.font = `${size}px ${family}`
  }
  ctx.fillText(text, canvas.width / 2, canvas.height / 2 + 10)
  return sampleCanvas(canvas, n, volume, true)
}

export async function sampleSvg(svgText: string, n: number, volume: Volume): Promise<Vec3[]> {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml')
  const svg = doc.documentElement
  if (svg.querySelector('parsererror') || svg.tagName.toLowerCase() !== 'svg') {
    return sampleText('SVG', n, volume)
  }
  const wrap = document.createElement('div')
  wrap.style.cssText = 'position:fixed;left:-4000px;top:0;width:800px;height:800px;opacity:0;pointer-events:none'
  wrap.appendChild(svg)
  document.body.appendChild(wrap)

  const candidates: Vec3[] = []
  const weights: number[] = []
  const geos = wrap.querySelectorAll('path, polygon, polyline, circle, ellipse, rect, line')
  geos.forEach((el) => {
    const geom = el as SVGGeometryElement
    if (typeof geom.getTotalLength !== 'function') return
    try {
      const len = geom.getTotalLength()
      if (!Number.isFinite(len) || len < 0.5) return
      const steps = Math.max(24, Math.ceil(len / 3))
      let prev = geom.getPointAtLength(0)
      for (let i = 0; i <= steps; i++) {
        const pt = geom.getPointAtLength((i / steps) * len)
        const step = Math.hypot(pt.x - prev.x, pt.y - prev.y)
        candidates.push({ x: pt.x, y: -pt.y, z: 0 })
        weights.push(1 + step)
        prev = pt
      }
    } catch {
      /* some SVG geometry elements throw */
    }
  })

  const blob = new Blob([svgText], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  try {
    const img = await loadImage(url)
    const canvas = document.createElement('canvas')
    canvas.width = 720
    canvas.height = 720
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, 720, 720)
      ctx.drawImage(img, 40, 40, 640, 640)
      const fill = sampleCanvas(canvas, Math.max(n * 2, 200), { ...volume, width: 2, height: 2, depth: 1, y0: 0 }, true)
      for (const p of fill) {
        candidates.push(p)
        weights.push(0.45)
      }
    }
  } finally {
    URL.revokeObjectURL(url)
    wrap.remove()
  }

  const picked = weights.length ? weightedPick(candidates, weights, n) : farthestPointSample(candidates, n)
  return fitToVolume(picked, volume, true)
}

export async function sampleImage(bitmap: ImageBitmap, n: number, volume: Volume): Promise<Vec3[]> {
  const canvas = document.createElement('canvas')
  const max = 720
  const scale = Math.min(max / bitmap.width, max / bitmap.height, 1)
  canvas.width = Math.max(32, Math.round(bitmap.width * scale))
  canvas.height = Math.max(32, Math.round(bitmap.height * scale))
  const ctx = canvas.getContext('2d')
  if (!ctx) return []
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  return sampleCanvas(canvas, n, volume, true)
}

function collectMeshCandidates(geometry: BufferGeometry, matrix: number[] | null, audience = { x: 0, y: 0, z: 1 }): { pts: Vec3[]; weights: number[] } {
  const pos = geometry.getAttribute('position')
  const nrm = geometry.getAttribute('normal')
  const index = geometry.getIndex()
  const pts: Vec3[] = []
  const weights: number[] = []
  if (!pos) return { pts, weights }

  const transform = (x: number, y: number, z: number) => {
    if (!matrix) return { x, y, z }
    const m = matrix
    return {
      x: m[0]! * x + m[4]! * y + m[8]! * z + m[12]!,
      y: m[1]! * x + m[5]! * y + m[9]! * z + m[13]!,
      z: m[2]! * x + m[6]! * y + m[10]! * z + m[14]!,
    }
  }

  const triCount = index ? index.count / 3 : pos.count / 3
  const budget = Math.min(8000, Math.max(400, triCount * 2))
  const step = Math.max(1, Math.floor(triCount / budget))

  for (let t = 0; t < triCount; t += step) {
    const ia = index ? index.getX(t * 3) : t * 3
    const ib = index ? index.getX(t * 3 + 1) : t * 3 + 1
    const ic = index ? index.getX(t * 3 + 2) : t * 3 + 2
    const a = transform(pos.getX(ia), pos.getY(ia), pos.getZ(ia))
    const b = transform(pos.getX(ib), pos.getY(ib), pos.getZ(ib))
    const c = transform(pos.getX(ic), pos.getY(ic), pos.getZ(ic))
    const abx = b.x - a.x
    const aby = b.y - a.y
    const abz = b.z - a.z
    const acx = c.x - a.x
    const acy = c.y - a.y
    const acz = c.z - a.z
    const nx = aby * acz - abz * acy
    const ny = abz * acx - abx * acz
    const nz = abx * acy - aby * acx
    const area = Math.hypot(nx, ny, nz)
    if (area < 1e-10) continue
    let fx = nx
    let fy = ny
    let fz = nz
    if (nrm) {
      fx = nrm.getX(ia)
      fy = nrm.getY(ia)
      fz = nrm.getZ(ia)
    }
    const facing = Math.max(0.12, (fx * audience.x + fy * audience.y + fz * audience.z) / (Math.hypot(fx, fy, fz) || 1))
    const samples = 1 + Math.round(facing * 2)
    for (let s = 0; s < samples; s++) {
      let u = Math.random()
      let v = Math.random()
      if (u + v > 1) {
        u = 1 - u
        v = 1 - v
      }
      const w = 1 - u - v
      pts.push({
        x: a.x * w + b.x * u + c.x * v,
        y: a.y * w + b.y * u + c.y * v,
        z: a.z * w + b.z * u + c.z * v,
      })
      weights.push(area * facing)
    }
  }
  return { pts, weights }
}

export async function sampleMesh(buffer: ArrayBuffer, ext: string, n: number, volume: Volume): Promise<Vec3[]> {
  const lower = ext.toLowerCase()
  const pts: Vec3[] = []
  const weights: number[] = []

  if (lower === 'stl') {
    const geo = new STLLoader().parse(buffer)
    const got = collectMeshCandidates(geo, null)
    pts.push(...got.pts)
    weights.push(...got.weights)
  } else if (lower === 'obj') {
    const text = new TextDecoder().decode(buffer)
    const group = new OBJLoader().parse(text)
    group.updateMatrixWorld(true)
    group.traverse((obj) => {
      const mesh = obj as Mesh
      if (!mesh.isMesh || !mesh.geometry) return
      const got = collectMeshCandidates(mesh.geometry, mesh.matrixWorld.elements as unknown as number[])
      pts.push(...got.pts)
      weights.push(...got.weights)
    })
  } else {
    const gltf = await new GLTFLoader().parseAsync(buffer, '')
    gltf.scene.updateMatrixWorld(true)
    gltf.scene.traverse((obj) => {
      const mesh = obj as Mesh
      if (!mesh.isMesh || !mesh.geometry) return
      const got = collectMeshCandidates(mesh.geometry, mesh.matrixWorld.elements as unknown as number[])
      pts.push(...got.pts)
      weights.push(...got.weights)
    })
  }

  const picked = weights.length ? weightedPick(pts, weights, n) : farthestPointSample(pts, n)
  return fitToVolume(picked, volume, false)
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('image load failed'))
    img.src = url
  })
}

export async function sampleClip(
  clip: Clip,
  n: number,
  volume: Volume,
  minSpacing = 2.5,
): Promise<{ points: Vec3[]; colors: Color[] }> {
  const color = hex(clip.color)
  let points: Vec3[] = []
  if (clip.kind === ClipKind.Motion) {
    return { points: [], colors: [] }
  }
  if (clip.kind === ClipKind.Preset && clip.preset) {
    points = samplePreset(clip.preset, n, volume, minSpacing)
  } else if (clip.kind === ClipKind.Text) {
    points = await sampleText(clip.text ?? clip.name, n, volume)
  } else if (clip.kind === ClipKind.Svg && clip.asset?.type === 'svg') {
    points = await sampleSvg(clip.asset.svgText, n, volume)
  } else if (clip.kind === ClipKind.Image && clip.asset?.type === 'image') {
    points = await sampleImage(clip.asset.bitmap, n, volume)
  } else if (clip.kind === ClipKind.Mesh && clip.asset?.type === 'mesh') {
    points = await sampleMesh(clip.asset.buffer, clip.asset.ext, n, volume)
  } else if (clip.text) {
    points = await sampleText(clip.text, n, volume)
  } else {
    points = samplePreset('heart', n, volume, minSpacing)
  }
  while (points.length < n) {
    const src = points[points.length % Math.max(1, points.length)] ?? { x: 0, y: volume.y0 + 10, z: 0 }
    points.push({
      x: src.x + (Math.random() - 0.5) * minSpacing,
      y: src.y + (Math.random() - 0.5) * minSpacing,
      z: src.z + (Math.random() - 0.5) * minSpacing * 0.3,
    })
  }
  const grounded = clip.preset === 'launch' || clip.preset === 'land'
  const spaced = grounded ? points.slice(0, n) : separatePoints(points.slice(0, n), minSpacing * 0.85, 6)
  return {
    points: spaced,
    colors: Array.from({ length: n }, () => ({ ...color })),
  }
}

export function volumeFromSettings(width: number, height: number, depth: number): Volume {
  return { width, height, depth, y0: 8 }
}
