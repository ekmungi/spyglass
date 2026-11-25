// RejectedList: the collapsed "Not of interest (N)" list under Suggested: every name that looks rejected
// now, which can each be taken back. The names rejected before this visit come first, then the ones
// struck through in a suggestion row on this visit, whose chips stay struck in their rows. A name taken
// back leaves the list at once, and its chip in a row, if it has one, opens again.
import type { WatchStatus } from '../../api/types'
import type { WatchEntry } from './api'
import type { SuggestionRow } from './organize'
import { decidedText } from './suggestionText'

export interface RejectedListProps {
  /** The names that were rejected when the page loaded, with the looks changed since. */
  rejected: WatchEntry[]
  /** The suggestion rows, with the looks changed since; their struck names are listed too. */
  rows: SuggestionRow[]
  /** Give one name a new status in place, with the toast to show after it. */
  change: (entity: WatchEntry, to: WatchStatus, done: string) => void
}

/** A closed fold with the count in its summary, a one-line explanation and a take-back chip per name. */
export function RejectedList({ rejected, rows, change }: RejectedListProps) {
  // One look per name: the list holds exactly the names that look rejected now, wherever they are shown.
  const shown = [...rejected, ...rows.flatMap((row) => row.entities)].filter((entity) => entity.status === 'rejected')
  return (
    <section aria-label="Not of interest" className="rw-section rw-section--fold">
      <details className="rw-fold">
        <summary>Not of interest ({shown.length})</summary>
        <div className="rw-fold__body">
          {shown.length > 0 ? (
            <>
              <p className="r-meta rw-fold__lead">These are never suggested again. Take a name back to allow it.</p>
              <div className="rw-chips">
                {shown.map((entity) => (
                  <span key={entity.id} className="rw-chip rw-chip--rej">
                    <button
                      type="button"
                      className="rw-chip__main rw-chip__take"
                      aria-label={`Take back ${entity.name}`}
                      onClick={() => change(entity, 'suggested', decidedText(entity, 'suggested'))}
                    >
                      <span className="rw-chip__name">{entity.name}</span>
                      <span className="rw-chip__back">Take back</span>
                    </button>
                  </span>
                ))}
              </div>
            </>
          ) : (
            <p className="r-meta">Nothing yet. A name you mark with the cross is listed here and is never suggested again.</p>
          )}
        </div>
      </details>
    </section>
  )
}
