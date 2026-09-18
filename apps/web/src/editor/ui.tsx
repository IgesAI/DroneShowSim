'use client'

import type { ReactNode, SVGProps } from 'react'

function Ico({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.25" {...props}>
      {children}
    </svg>
  )
}

export const Icon = {
  undo: (
    <Ico>
      <path d="M4 3 H2 V5" />
      <path d="M2.5 4.5 A4 4 0 1 1 3 9" />
    </Ico>
  ),
  redo: (
    <Ico>
      <path d="M8 3 H10 V5" />
      <path d="M9.5 4.5 A4 4 0 1 0 9 9" />
    </Ico>
  ),
  rewind: (
    <Ico>
      <path d="M2 2 V10" />
      <path d="M10 2 L4 6 L10 10 Z" fill="currentColor" stroke="none" />
    </Ico>
  ),
  prev: (
    <Ico>
      <path d="M7 2 L3 6 L7 10" />
      <path d="M10 2 L6 6 L10 10" />
    </Ico>
  ),
  next: (
    <Ico>
      <path d="M5 2 L9 6 L5 10" />
      <path d="M2 2 L6 6 L2 10" />
    </Ico>
  ),
  stepBack: (
    <Ico>
      <path d="M8 2 L4 6 L8 10" />
    </Ico>
  ),
  stepFwd: (
    <Ico>
      <path d="M4 2 L8 6 L4 10" />
    </Ico>
  ),
  play: (
    <Ico>
      <path d="M4 2 L10 6 L4 10 Z" fill="currentColor" stroke="none" />
    </Ico>
  ),
  pause: (
    <Ico>
      <path d="M3 2 H5 V10 H3 Z" fill="currentColor" stroke="none" />
      <path d="M7 2 H9 V10 H7 Z" fill="currentColor" stroke="none" />
    </Ico>
  ),
  loop: (
    <Ico>
      <path d="M8 2 H10 V4" />
      <path d="M10 3 A4 4 0 1 0 9.5 9" />
    </Ico>
  ),
  grid: (
    <Ico>
      <path d="M2 2 H10 V10 H2 Z" />
      <path d="M6 2 V10 M2 6 H10" />
    </Ico>
  ),
  bounds: (
    <Ico>
      <path d="M2 3 H10 V9 H2 Z" />
    </Ico>
  ),
  capsule: (
    <Ico>
      <circle cx="6" cy="6" r="3.5" />
    </Ico>
  ),
  path: (
    <Ico>
      <path d="M2 9 C4 4 8 8 10 3" />
    </Ico>
  ),
}

export function IconBtn({
  title,
  onClick,
  disabled,
  active,
  children,
}: {
  title: string
  onClick?: () => void
  disabled?: boolean
  active?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`grid h-6 w-6 place-items-center rounded-[2px] text-mute transition-colors duration-150 disabled:opacity-30 ${
        active ? 'bg-hover text-ink' : 'hover:bg-hover hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

export function GhostBtn({
  children,
  onClick,
  disabled,
  title,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  title?: string
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="h-6 rounded-[2px] px-2 text-[12px] text-mute hover:bg-hover hover:text-ink disabled:opacity-35"
    >
      {children}
    </button>
  )
}

export function Section({
  title,
  children,
  open = true,
}: {
  title: string
  children: ReactNode
  open?: boolean
}) {
  return (
    <details open={open} className="group">
      <summary className="flex h-6 cursor-pointer items-center px-2 text-[11px] text-faint select-none hover:text-mute">
        <span className="mr-1 inline-block w-2 text-[10px] text-faint group-open:rotate-90">›</span>
        {title}
      </summary>
      <div className="px-2 pb-2">{children}</div>
    </details>
  )
}

export function PropertyRow({
  label,
  unit,
  children,
}: {
  label: string
  unit?: string
  children: ReactNode
}) {
  return (
    <div className="grid h-6 grid-cols-[72px_minmax(0,1fr)_20px] items-center gap-1">
      <div className="truncate text-[12px] text-mute">{label}</div>
      {children}
      <div className="num text-right text-[11px] text-faint">{unit ?? ''}</div>
    </div>
  )
}

export function Field({
  value,
  onChange,
  type = 'text',
}: {
  value: string | number
  onChange: (v: string) => void
  type?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="num h-6 w-full rounded-[2px] bg-raised px-1 text-[12px] text-ink hover:bg-hover"
    />
  )
}

export function StatusMark({ tone }: { tone: 'ok' | 'warn' | 'hot' | 'idle' | 'accent' }) {
  if (tone === 'warn') {
    return <span className="inline-block h-1.5 w-1.5 rotate-45 bg-warn" title="Warning" />
  }
  if (tone === 'hot') {
    return <span className="inline-block h-2 w-1 bg-hot" title="Violation" />
  }
  const color = tone === 'ok' ? 'bg-ok' : tone === 'accent' ? 'bg-accent' : 'bg-faint'
  return <span className={`inline-block h-1.5 w-1.5 ${color}`} title={tone === 'ok' ? 'Valid' : 'Idle'} />
}

export function smpte(seconds: number, fps = 30) {
  const total = Math.max(0, Math.round(seconds * fps))
  const f = total % fps
  const s = Math.floor(total / fps) % 60
  const m = Math.floor(total / fps / 60) % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(m)}:${pad(s)}:${pad(f)}`
}

export function rulerTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`
}
