'use client'

import { useEffect, useMemo, useState } from 'react'
import { useEditor } from './store'

export function CommandMenu() {
  const open = useEditor((s) => s.paletteOpen)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!open) setQ('')
  }, [open])

  const items = useMemo(() => {
    const s = useEditor.getState()
    const all = [
      { id: 'play', label: 'Play / Pause', run: () => s.togglePlay() },
      { id: 'rewind', label: 'Rewind to start', run: () => s.rewind() },
      { id: 'demo', label: 'Load Dragon demo', run: () => void s.loadDemo(s.project?.droneProfile.count ?? 80) },
      { id: 'compile', label: 'Compile preview', run: () => void s.recompile() },
      { id: 'validate', label: 'Validate Show', run: () => void s.validate() },
      { id: 'audience', label: 'Toggle audience view', run: () => s.setAudienceView(!s.audienceView) },
      {
        id: 'engineering',
        label: 'Toggle engineering view',
        run: () => s.setViewMode(s.viewMode === 'engineering' ? 'show' : 'engineering'),
      },
      { id: 'grid', label: 'Toggle grid', run: () => s.setShowGrid(!s.showGrid) },
      { id: 'caps', label: 'Toggle safety capsules', run: () => s.setShowCapsules(!s.showCapsules) },
      { id: 'paths', label: 'Toggle velocity trajectories', run: () => s.setShowTrajectories(!s.showTrajectories) },
      { id: 'text', label: 'Create text formation…', run: () => {
        const t = window.prompt('Text formation')
        if (t) void s.addText(t)
      } },
    ]
    const n = q.trim().toLowerCase()
    return n ? all.filter((i) => i.label.toLowerCase().includes(n)) : all
  }, [q, open])

  if (!open) return null

  return (
    <div className="absolute inset-0 z-40 grid place-items-start bg-canvas/50 pt-[12vh]" onClick={() => useEditor.getState().setPaletteOpen(false)}>
      <div className="w-[400px] bg-panel" onClick={(e) => e.stopPropagation()}>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Command"
          className="h-8 w-full bg-raised px-3 text-[13px] text-ink"
          onKeyDown={(e) => {
            if (e.key === 'Escape') useEditor.getState().setPaletteOpen(false)
            if (e.key === 'Enter' && items[0]) {
              items[0].run()
              useEditor.getState().setPaletteOpen(false)
            }
          }}
        />
        <ul className="max-h-64 overflow-auto py-1">
          {items.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                className="block h-8 w-full px-3 text-left text-[12px] text-mute hover:bg-hover hover:text-ink"
                onClick={() => {
                  i.run()
                  useEditor.getState().setPaletteOpen(false)
                }}
              >
                {i.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
