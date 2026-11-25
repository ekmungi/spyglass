// ChipRow: one row of the Watch page: a heading on the left (a group, or later a profile section)
// and its chips on the right, wrapping. On a narrow window the chips go under the heading.
import type { ReactNode } from 'react'

export interface ChipRowProps {
  /** The id of the heading inside `head`, which names the row for screen readers. */
  labelledBy: string
  head: ReactNode
  /** Every chip in the row is switched off, so the heading is shown quieter. */
  quiet?: boolean
  children: ReactNode
}

/** A labelled group of chips with its heading. */
export function ChipRow({ labelledBy, head, quiet = false, children }: ChipRowProps) {
  return (
    <div className={`rw-chiprow${quiet ? ' rw-chiprow--quiet' : ''}`} role="group" aria-labelledby={labelledBy}>
      <div className="rw-chiprow__head">{head}</div>
      <div className="rw-chips">{children}</div>
    </div>
  )
}
