import JSZip from 'jszip'
import { evaluateShow, showDuration } from './evaluate'
import type { Clip, ShowSettings, Transition } from './types'

export type SerializableShow = {
  version: 1
  format: 'dshow'
  settings: ShowSettings
  origin: { lat: number; lon: number; alt: number }
  clips: {
    id: string
    name: string
    kind: string
    hold: number
    color: string
    preset?: string
    text?: string
    motion?: string
    points: [number, number, number][]
  }[]
  transitions: {
    id: string
    style: string
    duration: number
    assignment: number[]
  }[]
  constraints: {
    minSpacing: number
    maxVelocity: number
    maxAcceleration: number
  }
}

export function toDshow(clips: Clip[], transitions: Transition[], settings: ShowSettings): SerializableShow {
  return {
    version: 1,
    format: 'dshow',
    settings,
    origin: { lat: 0, lon: 0, alt: 0 },
    clips: clips.map((c) => ({
      id: c.id,
      name: c.name,
      kind: c.kind,
      hold: c.hold,
      color: c.color,
      preset: c.preset,
      text: c.text,
      motion: c.motion,
      points: (c.points ?? []).map((p) => [p.x, p.y, p.z]),
    })),
    transitions: transitions.map((t) => ({
      id: t.id,
      style: t.style,
      duration: t.duration,
      assignment: t.assignment ?? [],
    })),
    constraints: {
      minSpacing: settings.minSpacing,
      maxVelocity: settings.maxVelocity,
      maxAcceleration: settings.maxAcceleration,
    },
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function exportDshow(clips: Clip[], transitions: Transition[], settings: ShowSettings) {
  const doc = toDshow(clips, transitions, settings)
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
  downloadBlob(blob, 'show.dshow.json')
}

/** Skybrush CSV: Time_msec, x_m, y_m, z_m, Red, Green, Blue. Z-up, Y-forward. */
export async function exportSkybrushCsv(clips: Clip[], transitions: Transition[], settings: ShowSettings) {
  const duration = showDuration(clips, transitions)
  const fps = settings.fps
  const frames = Math.max(2, Math.round(duration * fps) + 1)
  const n = settings.droneCount
  const pos = new Float32Array(n * 3)
  const col = new Float32Array(n * 3)
  const rows: string[][] = Array.from({ length: n }, () => ['Time_msec,x_m,y_m,z_m,Red,Green,Blue'])

  for (let f = 0; f < frames; f++) {
    const t = f / fps
    evaluateShow(clips, transitions, settings, t, pos, col)
    const msec = Math.round(t * 1000)
    for (let i = 0; i < n; i++) {
      const x = pos[i * 3]!
      const yUp = pos[i * 3 + 1]!
      const zFwd = pos[i * 3 + 2]!
      const r = Math.round((col[i * 3] ?? 1) * 255)
      const g = Math.round((col[i * 3 + 1] ?? 1) * 255)
      const b = Math.round((col[i * 3 + 2] ?? 1) * 255)
      rows[i]!.push(`${msec},${x.toFixed(3)},${zFwd.toFixed(3)},${yUp.toFixed(3)},${r},${g},${b}`)
    }
  }

  const zip = new JSZip()
  rows.forEach((lines, i) => {
    zip.file(`drone_${String(i + 1).padStart(4, '0')}.csv`, lines.join('\n'))
  })
  zip.file(
    'README.txt',
    [
      'Dshow → Skybrush CSV export',
      '',
      'One CSV per drone. Columns: Time_msec, x_m, y_m, z_m, Red, Green, Blue',
      'Coordinates are Skybrush/Blender: X right, Y forward, Z up.',
      `Drones: ${n}`,
      `Duration: ${duration.toFixed(2)}s`,
      `Sample rate: ${fps} Hz`,
      '',
      'Import in Skybrush Studio via Formations → From zipped CSV files.',
    ].join('\n'),
  )
  const blob = await zip.generateAsync({ type: 'blob' })
  downloadBlob(blob, 'show-skybrush-csv.zip')
}
