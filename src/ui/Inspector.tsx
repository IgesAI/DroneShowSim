import { assignmentCost } from '../compiler/assign'
import { TransitionStyle } from '../compiler/types'
import { useShow } from '../store'

const STYLES = Object.values(TransitionStyle)

export function Inspector() {
  const clips = useShow((s) => s.clips)
  const transitions = useShow((s) => s.transitions)
  const selection = useShow((s) => s.selection)
  const safety = useShow((s) => s.safety)
  const updateClip = useShow((s) => s.updateClip)
  const updateTransition = useShow((s) => s.updateTransition)
  const useSuggestedDuration = useShow((s) => s.useSuggestedDuration)
  const removeSelected = useShow((s) => s.removeSelected)
  const exportJson = useShow((s) => s.exportJson)
  const exportCsv = useShow((s) => s.exportCsv)

  const clip = selection?.type === 'clip' ? clips.find((c) => c.id === selection.id) : undefined
  const transition = selection?.type === 'transition' ? transitions.find((t) => t.id === selection.id) : undefined
  const trIndex = transition ? transitions.findIndex((t) => t.id === transition.id) : -1
  const suggested = trIndex >= 0 ? safety?.minTransitionDurations[trIndex] : undefined
  const from = trIndex >= 0 ? clips[trIndex] : undefined
  const to = trIndex >= 0 ? clips[trIndex + 1] : undefined
  const cost =
    from?.points && to?.points && transition?.assignment
      ? assignmentCost(from.points, to.points, transition.assignment)
      : 0

  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="border-b border-line px-4 py-3">
        <div className="font-mono text-[10px] uppercase tracking-wider text-mute">Inspector</div>
        <div className="mt-1 text-sm">{clip?.name ?? (transition ? `${from?.name ?? 'A'} → ${to?.name ?? 'B'}` : 'Show')}</div>
      </div>
      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {clip && (
          <>
            <label className="block text-xs">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Name</span>
              <input
                className="w-full rounded-md border border-line bg-ink px-2 py-1.5"
                value={clip.name}
                onChange={(e) => updateClip(clip.id, { name: e.target.value })}
              />
            </label>
            {clip.kind === 'text' && (
              <label className="block text-xs">
                <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Text</span>
                <input
                  className="w-full rounded-md border border-line bg-ink px-2 py-1.5"
                  value={clip.text ?? ''}
                  onChange={(e) => updateClip(clip.id, { text: e.target.value, name: e.target.value.toUpperCase() })}
                />
              </label>
            )}
            <label className="block text-xs">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Hold {clip.hold.toFixed(1)}s</span>
              <input
                type="range"
                min={1}
                max={20}
                step={0.5}
                value={clip.hold}
                onChange={(e) => updateClip(clip.id, { hold: Number(e.target.value) })}
                className="w-full"
              />
            </label>
            <label className="block text-xs">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Color</span>
              <input
                type="color"
                value={clip.color}
                onChange={(e) => updateClip(clip.id, { color: e.target.value })}
                className="h-8 w-full rounded-md border border-line bg-ink"
              />
            </label>
            <button type="button" onClick={removeSelected} className="text-xs text-hot hover:underline">
              Remove clip
            </button>
          </>
        )}

        {transition && (
          <>
            <label className="block text-xs">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Style</span>
              <select
                className="w-full rounded-md border border-line bg-ink px-2 py-1.5 capitalize"
                value={transition.style}
                onChange={(e) => updateTransition(transition.id, { style: e.target.value as typeof transition.style })}
              >
                {STYLES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-mute">Duration {transition.duration.toFixed(1)}s</span>
              <input
                type="range"
                min={1}
                max={20}
                step={0.1}
                value={transition.duration}
                onChange={(e) => updateTransition(transition.id, { duration: Number(e.target.value) })}
                className="w-full"
              />
            </label>
            <div className="rounded-md border border-line bg-ink px-3 py-2 font-mono text-[11px] text-mute">
              Assignment travel {cost.toFixed(1)}m
              {suggested != null && (
                <div className="mt-1">Min safe {suggested.toFixed(1)}s</div>
              )}
            </div>
            {suggested != null && transition.duration < suggested && (
              <div className="rounded-md border border-hot/40 bg-hot/10 px-3 py-2 text-xs">
                <div className="font-medium text-hot">{transition.duration.toFixed(1)}s transition impossible</div>
                <div className="mt-1 text-mute">Minimum safe duration: {suggested.toFixed(1)}s</div>
                <button
                  type="button"
                  className="mt-2 rounded-md bg-ok px-2 py-1 text-ink"
                  onClick={() => useSuggestedDuration(transition.id, Math.ceil(suggested * 10) / 10)}
                >
                  Use {Math.ceil(suggested * 10) / 10} seconds
                </button>
              </div>
            )}
          </>
        )}

        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-mute">Safety</div>
          <div className="space-y-2">
            <div className="font-mono text-[11px] text-mute">
              Peak {safety?.peakVelocity.toFixed(1) ?? '—'} m/s · {safety?.peakAcceleration.toFixed(1) ?? '—'} m/s²
              <div>Min sep {safety?.minSeparation.toFixed(2) ?? '—'}m</div>
            </div>
            {(safety?.issues ?? []).map((issue) => (
              <div
                key={issue.message}
                className={`rounded-md border px-2 py-1.5 text-[11px] ${issue.level === 'error' ? 'border-hot/40 text-hot' : 'border-warn/40 text-warn'}`}
              >
                {issue.message}
              </div>
            ))}
            {safety?.ok && (safety.issues.length === 0) && (
              <div className="text-[11px] text-ok">Constraints satisfied.</div>
            )}
          </div>
        </div>
      </div>
      <div className="space-y-2 border-t border-line p-4">
        <button type="button" onClick={exportJson} className="w-full rounded-md border border-line px-3 py-2 text-left text-xs hover:border-ok/40">
          Export .dshow
        </button>
        <button type="button" onClick={() => void exportCsv()} className="w-full rounded-md bg-ok px-3 py-2 text-left text-xs text-ink">
          Export Skybrush CSV.zip
        </button>
      </div>
    </aside>
  )
}
