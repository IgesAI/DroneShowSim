import { useState } from 'react'
import { useShow } from '../store'

const EXAMPLE =
  '300 drones. Cobra motorcycle logo. Hold for five seconds. Transform into a motocross rider. Rider does a backflip. Transform into COBRA text. Red and white. Total show 45 seconds.'

export function PromptBar() {
  const [value, setValue] = useState('')
  const applyPrompt = useShow((s) => s.applyPrompt)

  return (
    <header className="flex items-center gap-3 border-b border-line bg-panel px-4 py-2.5">
      <div className="shrink-0">
        <div className="text-sm font-semibold tracking-wide">DSHOW</div>
        <div className="font-mono text-[10px] uppercase tracking-wider text-mute">Show compiler</div>
      </div>
      <form
        className="flex min-w-0 flex-1 items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          applyPrompt(value || EXAMPLE)
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={EXAMPLE}
          className="min-w-0 flex-1 rounded-md border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-ok/50"
        />
        <button type="submit" className="shrink-0 rounded-md bg-white px-3 py-2 text-xs font-medium text-ink">
          Generate
        </button>
      </form>
    </header>
  )
}
