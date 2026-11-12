// Pill: a small static label (a tier mark, a status, a count).
import type { ReactNode } from 'react'

export interface PillProps {
  tone?: 'neutral' | 'accent' | 'muted'
  title?: string
  children: ReactNode
}

/** A small non-interactive label; `accent` for emphasis, `muted` for text-only. */
export function Pill({ tone = 'neutral', title, children }: PillProps) {
  return (
    <span className={`r-pill r-pill--${tone}`} title={title}>
      {children}
    </span>
  )
}
