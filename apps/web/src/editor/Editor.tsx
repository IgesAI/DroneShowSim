'use client'

import { useEffect } from 'react'
import { CommandMenu } from './CommandMenu'
import { LeftPanel, RightPanel } from './Panels'
import { Timeline } from './Timeline'
import { Toolbar } from './Toolbar'
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
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      const s = useEditor.getState()
      // The conversion stage owns the viewport and its own keys. Leaving the
      // show shortcuts live would scrub a timeline nobody can see, and Delete
      // would remove a formation behind the overlay.
      if (s.conversion) return
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyK') {
        e.preventDefault()
        s.setPaletteOpen(!s.paletteOpen)
        return
      }
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ') {
        e.preventDefault()
        if (e.shiftKey) s.redo()
        else s.undo()
        return
      }
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyY') {
        e.preventDefault()
        s.redo()
        return
      }
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
        e.preventDefault()
        void s.recompile()
        return
      }
      if (typing) return
      if (e.code === 'Escape') {
        s.setPaletteOpen(false)
        s.setSelectedDrone(null)
      }
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
      if (e.code === 'KeyA') s.setAudienceView(!s.audienceView)
      if (e.code === 'KeyE') s.setViewMode(s.viewMode === 'engineering' ? 'show' : 'engineering')
      if (e.code === 'KeyG') s.setShowGrid(!s.showGrid)
      if (e.code === 'KeyT') s.setShowTrajectories(!s.showTrajectories)
      if (e.code === 'Digit1') s.setCameraPreset('persp')
      if (e.code === 'Digit2') s.setCameraPreset('top')
      if (e.code === 'Digit3') s.setCameraPreset('front')
      if (e.code === 'Digit4') s.setCameraPreset('side')
      if (e.code === 'Delete' || e.code === 'Backspace') {
        e.preventDefault()
        void s.removeSelected()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="relative flex h-full flex-col bg-chrome">
      <Toolbar />
      <div className="h-px bg-line-strong" />
      <div className="flex min-h-0 flex-1">
        <LeftPanel />
        <div className="w-px bg-line-strong" />
        <div className="flex min-w-0 flex-1 flex-col">
          <Viewport />
          <div className="h-px bg-line-strong" />
          <Timeline />
        </div>
        <div className="w-px bg-line-strong" />
        <RightPanel />
      </div>
      <CommandMenu />
    </div>
  )
}
