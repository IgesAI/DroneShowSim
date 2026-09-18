/** Lumina / dshow canonical types. Coordinates are DSHOW_LOCAL_RH meters. */

export const SCHEMA_VERSION = '0.2.0'
export const COMPILER_VERSION = '0.2.0'
export const COORDINATE_SYSTEM = 'DSHOW_LOCAL_RH'
export const COLOR_SPACE = 'linear-rgb'
export const CLOCK_DOMAIN = 'show-monotonic'

export type Vec3 = [number, number, number]
export type Rgb = [number, number, number]

export type TransitionType =
  | 'direct'
  | 'morph'
  | 'stagger'
  | 'explode'
  | 'collapse'
  | 'orbit'
  | 'wave'
  | 'umap'
  | 'auto'

export type SamplingMode =
  | 'outline'
  | 'fill'
  | 'feature'
  | 'surface'
  | 'silhouette'
  | 'wireframe'
  | 'audience'

export type AssetKind = 'svg' | 'png' | 'jpg' | 'glb' | 'obj' | 'stl' | 'text'
export type AltitudeDatum = 'local-z' | 'agl' | 'msl' | 'ellipsoid' | 'terrain'
export type ClockDomain = 'show-monotonic' | 'utc' | 'gps' | 'unix' | 'smpte'
export type ShowPhase = 'takeoff' | 'show' | 'rth' | 'landing'
export type ShowState = 'UNCOMPILED' | 'COMPILED' | 'VALIDATED' | 'ROBUSTNESS_TESTED' | 'EXPORTABLE'
export type GnssMode = 'rtk-fixed' | 'rtk-float' | 'gnss' | 'degraded'
export type FormationRole = 'launch' | 'artwork' | 'home'

export type DroneProfile = {
  name: string
  count: number
  /** Airframe / prop radius. Centers 2.5 m apart can still collide. */
  radiusM: number
  maxHorizontalSpeedMps: number
  maxVerticalSpeedMps: number
  maxAscentSpeedMps: number
  maxDescentSpeedMps: number
  maxAccelerationMps2: number
  maxJerkMps3: number
  minimumSeparationM: number
  /** Ground-grid pitch. Independent of in-air nav separation. */
  launchPitchM: number
  trajectoryHz: number
  lightingHz: number
  led: { type: 'RGB' | 'RGBW'; maximumBrightness: number }
}

export type AudienceCamera = {
  position: Vec3
  lookAt: Vec3
  heightM: number
  distanceM: number
  fovDeg: number
}

export type VenueConfiguration = {
  latitude: number
  longitude: number
  altitude: number
  altitudeDatum: AltitudeDatum
  groundZ: number
  showHeadingRad: number
  audience: AudienceCamera
}

export type SafetyProfile = {
  navigationUncertaintyM: number
  windAllowanceM: number
  operatorMarginM: number
  reactionTimeS: number
  velocitySeparationFactor: number
  launchPlacementErrorM: number
  rtkUncertaintyM: number
  gnssMode: GnssMode
  takeoffSeparationM: number
}

export type Transform = {
  translation: Vec3
  rotationRad: Vec3
  scale: Vec3
}

export type FormationPoint = {
  id: number
  position: Vec3
  color: Rgb
  importance: number
  sourceFeatureId?: number
}

export type FormationGenerationSettings = {
  mode: SamplingMode
  widthM: number
  heightM: number
  depthM: number
  seed: number
  samplerVersion?: number
  packScale?: number
}

export type Formation = {
  id: string
  name: string
  sourceAssetId: string
  role: FormationRole
  points: FormationPoint[]
  transform: Transform
  generationSettings: FormationGenerationSettings
}

export type Asset = {
  id: string
  name: string
  kind: AssetKind
  content: string
}

export type Cue = {
  id: string
  formationId: string
  startTime: number
  holdDuration: number
  phase: ShowPhase
}

export type DroneAssignment = {
  droneId: number
  fromPointId: number
  toPointId: number
}

export type Transition = {
  id: string
  fromFormationId: string
  toFormationId: string
  startTime: number
  duration: number
  durationMode: 'auto' | 'manual'
  type: TransitionType
  assignment: DroneAssignment[]
  trajectorySetId: string
}

export type AnimationKind = 'rigid' | 'procedural' | 'sequence'

export type AnimationMotion =
  | 'backflip'
  | 'orbit'
  | 'advance'
  | 'yaw'
  | 'wave'
  | 'flap'
  | 'pulse'
  | 'chroma'

export type AnimationClip = {
  id: string
  name: string
  kind: AnimationKind
  formationId: string
  cueOffset: number
  startTime: number
  duration: number
  loop: boolean
  motion: AnimationMotion
  amplitude: number
}

export type Timeline = {
  duration: number
  cues: Cue[]
  transitions: Transition[]
  animations: AnimationClip[]
}

export type ShowSlot = {
  droneId: number
  padIndex: number
  uavId?: string
}

export type CompilerNote = {
  kind: 'safety' | 'art' | 'info'
  message: string
  transitionId?: string
  time?: number
}

export type ShowProject = {
  version: string
  schemaVersion: string
  compilerVersion: string
  id: string
  name: string
  coordinateSystem: typeof COORDINATE_SYSTEM
  colorSpace: typeof COLOR_SPACE
  clockDomain: ClockDomain
  showState: ShowState
  droneProfile: DroneProfile
  venue: VenueConfiguration
  assets: Asset[]
  formations: Formation[]
  timeline: Timeline
  safetyProfile: SafetyProfile
  slots: ShowSlot[]
  compilerNotes: CompilerNote[]
  proximityViolations: Violation[]
}

export type SafetyMeasurement = {
  value: number
  limit: number
  passed: boolean
}

export type Violation = {
  droneIds: number[]
  time: number
  positions: Vec3[]
  measured: number
  required: number
  severity: 'warn' | 'error'
  message: string
  phase?: ShowPhase
  closingSpeedMps?: number
}

export type SafetyReport = {
  passed: boolean
  minimumSeparation: SafetyMeasurement
  maxHorizontalVelocity: SafetyMeasurement
  maxVerticalVelocity: SafetyMeasurement
  maxAcceleration: SafetyMeasurement
  maxJerk: SafetyMeasurement
  altitudeViolations: Violation[]
  geofenceViolations: Violation[]
  proximityViolations: Violation[]
  recommendedDuration?: number
}

export type CompiledTransition = {
  transitionId: string
  duration: number
  assignment: number[]
  status: 'SAFE' | 'MODIFIED' | 'UNSAFE'
  safety: SafetyReport
}

export const defaultAudience = (): AudienceCamera => ({
  position: [0, 90, 1.7],
  lookAt: [0, 0, 28],
  heightM: 1.7,
  distanceM: 90,
  fovDeg: 38,
})

export const defaultDroneProfile = (count = 250): DroneProfile => ({
  name: 'generic-show-drone',
  count,
  radiusM: 0.2,
  maxHorizontalSpeedMps: 8,
  maxVerticalSpeedMps: 4,
  maxAscentSpeedMps: 4,
  maxDescentSpeedMps: 3,
  maxAccelerationMps2: 3,
  maxJerkMps3: 6,
  minimumSeparationM: 2.5,
  launchPitchM: 4,
  trajectoryHz: 20,
  lightingHz: 50,
  led: { type: 'RGB', maximumBrightness: 1 },
})

export const defaultSafetyProfile = (): SafetyProfile => ({
  navigationUncertaintyM: 0.3,
  windAllowanceM: 0.2,
  operatorMarginM: 0.3,
  reactionTimeS: 0.25,
  velocitySeparationFactor: 0.12,
  launchPlacementErrorM: 0.15,
  rtkUncertaintyM: 0.03,
  gnssMode: 'rtk-fixed',
  takeoffSeparationM: 3.5,
})

export const identityTransform = (): Transform => ({
  translation: [0, 0, 25],
  rotationRad: [0, 0, 0],
  scale: [1, 1, 1],
})

/** Invisible safety capsule around each airframe. */
export function capsuleRadiusM(profile: DroneProfile, safety: SafetyProfile): number {
  return (
    profile.radiusM +
    safety.navigationUncertaintyM +
    safety.windAllowanceM +
    safety.operatorMarginM +
    (safety.gnssMode === 'rtk-fixed' ? safety.rtkUncertaintyM : 0)
  )
}

/** Stationary center-to-center requirement (volumes, not points). */
export function baseSeparationM(profile: DroneProfile, safety: SafetyProfile): number {
  return (
    profile.minimumSeparationM +
    capsuleRadiusM(profile, safety) * 2 -
    profile.radiusM * 2 +
    profile.radiusM * 2
  )
}

export function requiredSeparationM(profile: DroneProfile, safety: SafetyProfile, closingSpeedMps = 0): number {
  return (
    profile.minimumSeparationM +
    profile.radiusM * 2 +
    safety.navigationUncertaintyM +
    safety.windAllowanceM +
    safety.operatorMarginM +
    Math.max(0, closingSpeedMps) * safety.velocitySeparationFactor
  )
}

export function dynamicCapsuleRadiusM(profile: DroneProfile, safety: SafetyProfile, speedMps: number): number {
  return capsuleRadiusM(profile, safety) + Math.max(0, speedMps) * safety.velocitySeparationFactor * 0.5
}
