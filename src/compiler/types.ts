export type Vec3 = { x: number; y: number; z: number }
export type Color = { r: number; g: number; b: number }

export const TransitionStyle = {
  Auto: 'auto',
  Direct: 'direct',
  Morph: 'morph',
  Explode: 'explode',
  Collapse: 'collapse',
  Orbit: 'orbit',
  Wave: 'wave',
  Dissolve: 'dissolve',
  Umap: 'umap',
  Fluid: 'fluid',
  Vortex: 'vortex',
} as const

export type TransitionStyle = (typeof TransitionStyle)[keyof typeof TransitionStyle]

export const ClipKind = {
  Preset: 'preset',
  Svg: 'svg',
  Image: 'image',
  Mesh: 'mesh',
  Text: 'text',
  Motion: 'motion',
} as const

export type ClipKind = (typeof ClipKind)[keyof typeof ClipKind]

export const PresetName = {
  Launch: 'launch',
  Land: 'land',
  Heart: 'heart',
  Star: 'star',
  Ring: 'ring',
  Eagle: 'eagle',
  Rider: 'rider',
  Cobra: 'cobra',
  Burst: 'burst',
} as const

export type PresetName = (typeof PresetName)[keyof typeof PresetName]

export const MotionName = {
  Backflip: 'backflip',
  Orbit: 'orbit',
  Wave: 'wave',
} as const

export type MotionName = (typeof MotionName)[keyof typeof MotionName]

export type Volume = {
  width: number
  height: number
  depth: number
  y0: number
}

export type ShowSettings = {
  droneCount: number
  width: number
  height: number
  depth: number
  minSpacing: number
  maxVelocity: number
  maxAcceleration: number
  fps: number
}

export type ClipAsset =
  | { type: 'svg'; name: string; svgText: string }
  | { type: 'image'; name: string; bitmap: ImageBitmap }
  | { type: 'mesh'; name: string; buffer: ArrayBuffer; ext: string }

export type Clip = {
  id: string
  name: string
  kind: ClipKind
  hold: number
  color: string
  preset?: PresetName
  text?: string
  motion?: MotionName
  asset?: ClipAsset
  points: Vec3[] | null
  colors: Color[] | null
}

export type Transition = {
  id: string
  style: TransitionStyle
  duration: number
  assignment: number[] | null
}

export type SafetyIssue = {
  level: 'warn' | 'error'
  message: string
  clipId?: string
  transitionId?: string
  suggestedDuration?: number
}

export type SafetyReport = {
  ok: boolean
  minTransitionDurations: number[]
  issues: SafetyIssue[]
  peakVelocity: number
  peakAcceleration: number
  minSeparation: number
}

export type ShowDocument = {
  version: 1
  settings: ShowSettings
  clips: Clip[]
  transitions: Transition[]
}
