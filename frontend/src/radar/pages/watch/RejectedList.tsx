// RejectedList: the collapsed "Not of interest (N)" list under Suggested: the names rejected before this
// visit, each of which can be taken back. A name taken back leaves the list at once, and Undo puts it
// back where it was; names struck through on this visit join the list on the next one.
import type { WatchStatus } from '../../api/types'
import type { WatchEntry } from './api'
import { takenBackText } from './suggestionText'

export interface RejectedListProps {
  /** The names that were rejected when the page loaded, with the looks changed since. */
  rejected: WatchEntry[]
  /** Give one name a new status in place, with the toast to show after it. */
  change: (entity: WatchEntry, to: WatchStatus, done: string) => void
}

/** A closed fold with the count in its summary, a one-line explanation and a take-back chip per name. */
export function RejectedList({ rejected, change }: RejectedListProps) {
  // A name taken back on this visit looks "suggested" now and is left out until Undo.
  const shown = rejected.filter((entity) => entity.status === 'rejected')
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
                      onClick={() => change(entity, 'suggested', takenBackText(entity))}
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
