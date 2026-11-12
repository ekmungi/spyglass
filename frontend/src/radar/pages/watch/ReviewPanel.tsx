// ReviewPanel: "Review with AI". Asks the service to look over the register and shows what it
// proposes as checklists. Nothing is ticked at first and nothing changes until "Apply selected".
import { useEffect, useId, useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { WatchApplyResponse, WatchReview } from '../../api/types'
import { Button, Dialog } from '../../ui'
import { useElapsed } from '../sources/useElapsed'
import { applyWatchReview, reviewWatch } from './api'
import { reviewRows, selectionBody } from './reviewRows'

export interface ReviewPanelProps {
  onClose: () => void
  /** The apply succeeded; the page shows the toast and keeps the new register. */
  onApplied: (result: WatchApplyResponse) => void
}

/** Mount it only while open: it starts the review on mount and forgets everything on close. */
export function ReviewPanel({ onClose, onApplied }: ReviewPanelProps) {
  const [review, setReview] = useState<WatchReview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [round, setRound] = useState(0)
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set())
  const [applying, setApplying] = useState(false)
  const [applyProblem, setApplyProblem] = useState<string | null>(null)
  const waiting = review === null && error === null
  const seconds = useElapsed(waiting)
  const base = useId()

  useEffect(() => {
    const controller = new AbortController()
    reviewWatch(controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) setReview(result)
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(cause))
      },
    )
    return () => controller.abort()
  }, [round])

  const retry = () => {
    setError(null)
    setReview(null)
    setRound((value) => value + 1)
  }

  const toggle = (key: string) =>
    setTicked((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })

  const apply = async () => {
    if (!review) return
    setApplying(true)
    setApplyProblem(null)
    try {
      onApplied(await applyWatchReview(selectionBody(review, ticked)))
    } catch (cause) {
      setApplyProblem(errorMessage(cause))
      setApplying(false)
    }
  }

  const sections = review ? reviewRows(review) : []
  return (
    <Dialog
      open
      onClose={onClose}
      title="Review with AI"
      footer={
        review && sections.length > 0 ? (
          <>
            <span className="r-meta rw-review__count">{ticked.size === 0 ? 'Nothing ticked' : `${ticked.size} ticked`}</span>
            <Button variant="quiet" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={ticked.size === 0 || applying} onClick={() => void apply()}>
              Apply selected
            </Button>
          </>
        ) : review ? (
          <Button variant="primary" onClick={onClose}>
            Close
          </Button>
        ) : undefined
      }
    >
      <div className="rw-review">
        <div role="status" aria-live="polite">
          {waiting && (
            <p className="r-meta">
              Reading your watch list and the last month of news. This can take up to a minute ({seconds}s so far). Nothing changes until you choose.
            </p>
          )}
        </div>
        {error && (
          <div className="rw-error r-appear" role="alert">
            <p className="r-error-text">{error}</p>
            <Button onClick={retry}>Try again</Button>
          </div>
        )}
        {review && (
          <div className="rw-review r-appear">
            <p className="rw-review__summary">{review.summary}</p>
            {review.note && <p className="r-meta">{review.note}</p>}
            {sections.length === 0 && <p className="r-meta">There is nothing to change right now.</p>}
            <div className="rw-review__body">
              {sections.map((section) => (
                <fieldset key={section.kind} className="rw-check-group">
                  <legend>{section.legend}</legend>
                  {section.hint && <p className="r-meta">{section.hint}</p>}
                  {section.rows.map((row, index) => {
                    const id = `${base}-${section.kind}-${index}`
                    return (
                      <div key={row.key} className="rw-check">
                        <input id={id} type="checkbox" checked={ticked.has(row.key)} disabled={applying} onChange={() => toggle(row.key)} />
                        <div>
                          <label htmlFor={id}>
                            <span className="rw-check__name">{row.label}</span>
                            {row.meta && <span className="r-meta"> {row.meta}</span>}
                          </label>
                          {row.reason && <p className="rw-why">{row.reason}</p>}
                        </div>
                      </div>
                    )
                  })}
                </fieldset>
              ))}
            </div>
            {applyProblem && (
              <p className="r-error-text" role="alert">
                {applyProblem}
              </p>
            )}
          </div>
        )}
      </div>
    </Dialog>
  )
}
