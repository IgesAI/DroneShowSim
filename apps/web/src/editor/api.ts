import type { ShowProject, Violation } from '@lumina/schema'

export type CompileResult = { project: ShowProject; violations: Violation[] }

const BASE = process.env.NEXT_PUBLIC_COMPILER_URL ?? 'http://localhost:8000'

async function request(path: string, init: RequestInit = {}, timeoutMs = 180_000): Promise<Response> {
  try {
    return await fetch(`${BASE}${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      throw new Error('dshowc timed out. The compiler may still be working — try again in a few seconds.')
    }
    throw new Error('Cannot reach dshowc on http://localhost:8000. Start the compiler API, then reload.')
  }
}

async function parseJson(res: Response) {
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

export async function pingCompiler(): Promise<boolean> {
  const res = await request('/health', { method: 'GET' }, 4000)
  const data = await parseJson(res)
  return Boolean(data.ok)
}

export async function compileDemo(count = 250, seed = 1): Promise<CompileResult> {
  const res = await request(`/shows/demo?count=${count}&seed=${seed}`, { method: 'POST' })
  const data = await parseJson(res)
  return { project: data.project as ShowProject, violations: (data.violations ?? []) as Violation[] }
}

export async function compileShow(project: ShowProject, mode: 'preview' | 'full' = 'preview'): Promise<CompileResult> {
  const res = await request('/shows/compile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, mode }),
  })
  const data = await parseJson(res)
  return { project: data.project as ShowProject, violations: (data.violations ?? []) as Violation[] }
}

export async function generateFormation(body: {
  assetId: string
  name: string
  content: string
  kind: 'svg' | 'text' | 'glb' | 'obj' | 'stl'
  mode?: 'feature' | 'surface' | 'silhouette' | 'audience'
  depthMeters?: number
  droneCount: number
  widthMeters: number
  heightMeters: number
  seed: number
}) {
  const res = await request(
    '/formations/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    30_000,
  )
  return parseJson(res)
}

async function download(path: string, project: ShowProject, filename: string) {
  const res = await request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project }),
  })
  if (!res.ok) throw new Error(await res.text())
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export const exportGenericCsv = (p: ShowProject) => download('/exports/csv', p, 'show-generic.csv.zip')
export const exportVviz = (p: ShowProject) => download('/exports/vviz', p, 'show.vviz')
export const exportSkybrush = (p: ShowProject) => download('/exports/skybrush-csv', p, 'show-skybrush-csv.zip')
export const exportDshow = (p: ShowProject) => download('/exports/dshow', p, 'show.dshow')
