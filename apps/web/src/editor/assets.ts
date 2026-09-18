export type ImportKind = 'svg' | 'glb' | 'obj' | 'stl' | 'text'

const MESH = new Set(['glb', 'obj', 'stl'])

export function extOf(name: string): string {
  return name.split('.').pop()?.toLowerCase() ?? ''
}

export function kindFromName(name: string): ImportKind | null {
  const ext = extOf(name)
  if (ext === 'svg' || ext === 'glb' || ext === 'obj' || ext === 'stl') return ext
  return null
}

export function acceptFiles(): string {
  return '.svg,.glb,.obj,.stl,image/svg+xml,model/gltf-binary'
}

export async function readAssetFile(file: File): Promise<{ name: string; kind: ImportKind; content: string }> {
  const kind = kindFromName(file.name)
  if (!kind) throw new Error('Use SVG, GLB, OBJ, or STL. PNG raster sampling is not compiled yet.')
  const stem = file.name.replace(/\.[^.]+$/, '')
  if (kind === 'svg' || kind === 'obj') {
    return { name: stem, kind, content: await file.text() }
  }
  const buf = await file.arrayBuffer()
  const bytes = new Uint8Array(buf)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]!)
  const mime = kind === 'glb' ? 'model/gltf-binary' : 'model/stl'
  return { name: stem, kind, content: `data:${mime};base64,${btoa(binary)}` }
}

export function isMesh(kind: ImportKind): boolean {
  return MESH.has(kind)
}
