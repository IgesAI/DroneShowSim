'use client'

import { useEffect } from 'react'
import { LeftPanel, RightPanel } from './Panels'
import { Timeline } from './Timeline'
import { Viewport } from './Viewport'
import { pingCompiler } from './api'
import { useEditor } from './store'

let editorBootstrapped = false

export function Editor() {
  const loadDemo = useEditor((s) => s.loadDemo)

  useEffect(() => {
    if (editorBootstrapped) return
    editorBootstrapped = true
    void (async () => {
      try {
        await pingCompiler()
        await loadDemo(80)
      } catch (err) {
        editorBootstrapped = false
        useEditor.setState({
          compiling: false,
          error: err instanceof Error ? err.message : 'Cannot reach dshowc on port 8000',
        })
      }
    })()
  }, [loadDemo])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const s = useEditor.getState()
      if (e.code === 'Space') {
        e.preventDefault()
        s.togglePlay()
      }
      if (e.code === 'KeyK') s.pause()
      if (e.code === 'Home' || e.code === 'Digit0' || e.code === 'KeyR') {
        e.preventDefault()
        s.rewind()
      }
      if (e.code === 'KeyJ' || e.code === 'ArrowUp') {
        e.preventDefault()
        s.skipCue(-1)
      }
      if (e.code === 'KeyL' || e.code === 'ArrowDown') {
        e.preventDefault()
        s.skipCue(1)
      }
      if (e.code === 'ArrowLeft') {
        e.preventDefault()
        s.stepFrame(-1)
      }
      if (e.code === 'ArrowRight') {
        e.preventDefault()
        s.stepFrame(1)
      }
      if (e.code === 'Delete' || e.code === 'Backspace') {
        e.preventDefault()
        void s.removeSelected()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="relative flex h-full flex-col bg-[#111827]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(ellipse_at_top,_rgb(79_70_229_/_0.22),_transparent_60%)]" />
      <header className="relative z-10 flex items-center justify-between border-b border-white/10 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded-full bg-indigo-600 text-xs font-semibold text-white glow-btn">L</div>
          <div>
            <div className="font-[family-name:var(--font-display)] text-sm font-semibold text-white">
              Lumina <span className="hero-gradient">compiler</span>
            </div>
            <div className="text-[11px] text-gray-400">Gorzen Engineering · dshowc</div>
          </div>
        </div>
        <div className="hidden text-[11px] text-gray-400 md:block">geometry → assignment → animation → safety</div>
      </header>
      <div className="relative z-10 flex min-h-0 flex-1">
        <LeftPanel />
        <div className="flex min-w-0 flex-1 flex-col">
          <Viewport />
          <Timeline />
        </div>
        <RightPanel />
      </div>
    </div>
  )
}
