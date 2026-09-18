import { useEffect } from 'react'
import { useShow } from './store'
import { Inspector } from './ui/Inspector'
import { PromptBar } from './ui/PromptBar'
import { Settings } from './ui/Settings'
import { Timeline } from './ui/Timeline'
import { Viewport } from './ui/Viewport'

export function App() {
  const rebuild = useShow((s) => s.rebuild)
  const togglePlay = useShow((s) => s.togglePlay)
  const setPlayhead = useShow((s) => s.setPlayhead)
  const setPlaying = useShow((s) => s.setPlaying)

  useEffect(() => {
    void rebuild()
  }, [rebuild])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.code === 'Space') {
        e.preventDefault()
        togglePlay()
      }
      if (e.code === 'Home') {
        setPlaying(false)
        setPlayhead(0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPlayhead, setPlaying, togglePlay])

  return (
    <div className="flex h-full flex-col">
      <PromptBar />
      <div className="flex min-h-0 flex-1">
        <Settings />
        <div className="flex min-w-0 flex-1 flex-col">
          <Viewport />
          <Timeline />
        </div>
        <Inspector />
      </div>
    </div>
  )
}
