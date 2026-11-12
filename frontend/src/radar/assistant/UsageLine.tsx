// UsageLine: under an assistant answer, one quiet line about its token use (shown on hover or
// focus) and, when the conversation was condensed for this turn, a note saying so.
import { useEffect, useState } from 'react'
import { loadMessageUsage } from '../api/usage'
import type { UsageFigures } from '../api/usageTypes'
import './usage.css'
import { CONDENSED_NOTE, describeUsage } from './usageText'

/** The usage of a stored answer; renders nothing until the figures arrive or when there are none. */
export function UsageLine({ messageId, finished }: { messageId: number | null; finished: boolean }) {
  const [figures, setFigures] = useState<UsageFigures | null>(null)

  useEffect(() => {
    if (!finished || messageId === null) return
    const controller = new AbortController()
    loadMessageUsage(messageId, controller.signal).then(
      (found) => {
        if (!controller.signal.aborted) setFigures(found)
      },
      () => undefined, // the line is a courtesy: a failed request just leaves it out
    )
    return () => controller.abort()
  }, [finished, messageId])

  if (!figures) return null
  const line = describeUsage(figures)
  return (
    <>
      {figures.condensed && <p className="r-msg__note">{CONDENSED_NOTE}</p>}
      {line && (
        <p className="r-usage" data-testid="usage-line">
          {line}
        </p>
      )}
    </>
  )
}
