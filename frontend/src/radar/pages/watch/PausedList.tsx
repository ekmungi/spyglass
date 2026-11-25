// PausedList: the collapsed "Paused (N)" list under the groups: every name that was paused when the
// page loaded, each labelled with its group. A click watches a name again and the chip stays here.
import { Fragment, type ReactNode } from 'react'
import type { PausedName } from './organize'

export interface PausedListProps {
  paused: PausedName[]
  /** One chip for a paused name; the page supplies it so the chip behaves as in the groups. */
  chip: (name: PausedName) => ReactNode
}

/** A closed fold with the count in its summary, a one-line explanation and the chips. */
export function PausedList({ paused, chip }: PausedListProps) {
  return (
    <details className="rw-fold">
      <summary>Paused ({paused.length})</summary>
      <div className="rw-fold__body">
        {paused.length > 0 ? (
          <>
            <p className="r-meta rw-fold__lead">Spyglass does not search for these. Click a name to watch it again.</p>
            <div className="rw-chips">
              {paused.map((name) => (
                <Fragment key={name.entity.id}>{chip(name)}</Fragment>
              ))}
            </div>
          </>
        ) : (
          <p className="r-meta">Nothing is paused.</p>
        )}
      </div>
    </details>
  )
}
