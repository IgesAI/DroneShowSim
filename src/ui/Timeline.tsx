import { buildSpans } from '../compiler/evaluate'
import { smpte } from '../compiler/math'
import { useShow } from '../store'

export function Timeline() {
  const clips = useShow((s) => s.clips)
  const transitions = useShow((s) => s.transitions)
  const playhead = useShow((s) => s.playhead)
  const duration = useShow((s) => s.duration)
  const playing = useShow((s) => s.playing)
  const selection = useShow((s) => s.selection)
  const setPlayhead = useShow((s) => s.setPlayhead)
  const togglePlay = useShow((s) => s.togglePlay)
  const select = useShow((s) => s.select)
  const setPlaying = useShow((s) => s.setPlaying)

  const spans = buildSpans(clips, transitions)
  const total = Math.max(duration, 0.001)

  return (
    <div className="border-t border-line bg-panel">
      <div className="flex items-center gap-3 px-4 py-2">
        <button
          type="button"
          onClick={togglePlay}
          className="grid h-8 w-8 place-items-center rounded-md bg-ok text-ink"
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="font-mono text-sm tabular-nums">{smpte(playhead)}</div>
        <div className="text-mute">/</div>
        <div className="font-mono text-sm text-mute tabular-nums">{smpte(duration)}</div>
        <button type="button" className="text-xs text-mute hover:text-white" onClick={() => { setPlaying(false); setPlayhead(0) }}>
          00:00:00:00
        </button>
      </div>
      <div
        className="relative mx-4 mb-3 h-[76px] cursor-pointer overflow-hidden rounded-lg bg-ink"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          setPlayhead(((e.clientX - rect.left) / rect.width) * total)
        }}
      >
        {spans.map((span) => {
          const left = (span.start / total) * 100
          const width = ((span.end - span.start) / total) * 100
          if (span.kind === 'clip') {
            const clip = clips[span.clipIndex]
            if (!clip) return null
            const on = selection?.type === 'clip' && selection.id === clip.id
            return (
              <button
                key={clip.id}
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  select({ type: 'clip', id: clip.id })
                  setPlayhead(span.start + Math.min(0.25, clip.hold * 0.2))
                }}
                className="absolute top-2 h-10 overflow-hidden rounded-md border px-2 text-left text-[11px] font-medium"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  background: `${clip.color}22`,
                  borderColor: on ? '#7cffb2' : `${clip.color}66`,
                  color: '#f4f1ea',
                }}
              >
                <div className="truncate">{clip.name}</div>
                <div className="truncate font-mono text-[10px] text-mute">{clip.kind}</div>
              </button>
            )
          }
          const tr = transitions[span.transitionIndex]
          if (!tr) return null
          const on = selection?.type === 'transition' && selection.id === tr.id
          return (
            <button
              key={tr.id}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                select({ type: 'transition', id: tr.id })
                setPlayhead(span.start + (span.end - span.start) * 0.45)
              }}
              className="absolute top-[50px] h-5 overflow-hidden rounded-sm border px-1 font-mono text-[9px] uppercase tracking-wider"
              style={{
                left: `${left}%`,
                width: `${width}%`,
                borderColor: on ? '#ffb020' : '#2a3038',
                background: on ? '#ffb02022' : '#ffffff08',
                color: '#8b939e',
              }}
            >
              {tr.style}
            </button>
          )
        })}
        <div
          className="pointer-events-none absolute top-0 z-10 h-full w-px bg-ok"
          style={{ left: `${(playhead / total) * 100}%` }}
        />
      </div>
    </div>
  )
}
