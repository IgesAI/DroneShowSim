import { useShow } from '../store'

function Field({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  suffix: string
  onChange: (n: number) => void
}) {
  return (
    <label className="block">
      <div className="mb-1 flex justify-between font-mono text-[10px] uppercase tracking-wider text-mute">
        <span>{label}</span>
        <span className="text-white">{value}{suffix}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </label>
  )
}

export function Settings() {
  const settings = useShow((s) => s.settings)
  const patchSettings = useShow((s) => s.patchSettings)
  const addPreset = useShow((s) => s.addPreset)
  const importFiles = useShow((s) => s.importFiles)
  const compiling = useShow((s) => s.compiling)

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-panel">
      <div className="border-b border-line px-4 py-3">
        <div className="font-mono text-[10px] uppercase tracking-wider text-mute">Show settings</div>
        <div className="mt-1 text-sm text-mute">{compiling ? 'Resampling formations…' : 'Constraints drive the compiler'}</div>
      </div>
      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <Field label="Drones" value={settings.droneCount} min={40} max={1200} step={10} suffix="" onChange={(n) => patchSettings({ droneCount: n })} />
        <Field label="Width" value={settings.width} min={40} max={400} step={5} suffix="m" onChange={(n) => patchSettings({ width: n })} />
        <Field label="Height" value={settings.height} min={20} max={250} step={5} suffix="m" onChange={(n) => patchSettings({ height: n })} />
        <Field label="Depth" value={settings.depth} min={20} max={250} step={5} suffix="m" onChange={(n) => patchSettings({ depth: n })} />
        <Field label="Min spacing" value={settings.minSpacing} min={1} max={8} step={0.1} suffix="m" onChange={(n) => patchSettings({ minSpacing: n })} />
        <Field label="Max velocity" value={settings.maxVelocity} min={2} max={20} step={0.5} suffix="m/s" onChange={(n) => patchSettings({ maxVelocity: n })} />
        <Field label="Max accel" value={settings.maxAcceleration} min={1} max={10} step={0.1} suffix="m/s²" onChange={(n) => patchSettings({ maxAcceleration: n })} />
        <div className="border-t border-line pt-4">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-mute">Add formation</div>
          <div className="grid grid-cols-2 gap-1.5">
            {(['heart', 'eagle', 'rider', 'cobra', 'star', 'ring', 'burst'] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => addPreset(p)}
                className="rounded-md border border-line px-2 py-1.5 text-left text-xs capitalize hover:border-ok/40"
              >
                {p}
              </button>
            ))}
            <button type="button" onClick={() => addPreset('text')} className="rounded-md border border-line px-2 py-1.5 text-left text-xs hover:border-ok/40">
              Text
            </button>
            <label className="rounded-md border border-dashed border-line px-2 py-1.5 text-xs text-mute hover:border-ok/40">
              Import
              <input
                type="file"
                className="hidden"
                multiple
                accept=".svg,.png,.jpg,.jpeg,.webp,.glb,.gltf,.obj,.stl"
                onChange={(e) => {
                  void importFiles([...(e.target.files ?? [])])
                  e.target.value = ''
                }}
              />
            </label>
          </div>
        </div>
        <p className="text-[11px] leading-relaxed text-mute">
          Audience-facing sampling is automatic for meshes. SVG and images use an importance map so detail (eyes, edges, letterforms) gets more drones than empty fill.
        </p>
      </div>
    </aside>
  )
}
