// Brief states: the "You are caught up" end marker, the no-brief empty state with Compose now,
// and the loading skeleton.
import { useState } from 'react'
import { generateBrief } from '../api/client'
import { errorMessage } from '../api/errors'
import type { BriefDoc } from '../api/types'
import { buildHash, navigate } from '../router'
import { Button, EmptyState, Skeleton } from '../ui'

/** The end of the brief: caught up, how much was filtered, and the way to the Feed. */
export function CaughtUp({ filteredOut }: { filteredOut: number }) {
  const feedRoute = { name: 'feed' as const, params: { tier: 'all' } }
  return (
    <footer className="r-caught-up" data-testid="caught-up">
      <p className="r-caught-up__title">You are caught up.</p>
      <p className="r-caught-up__body">
        {filteredOut > 0 ? `${filteredOut} other items were filtered out as noise. ` : ''}
        <a
          href={buildHash(feedRoute)}
          onClick={(event) => {
            event.preventDefault()
            navigate(feedRoute)
          }}
        >
          {filteredOut > 0 ? 'See everything in the Feed' : 'Open the Feed'}
        </a>
      </p>
    </footer>
  )
}

/** No brief yet: explain, offer Compose now, and show progress while it runs. */
export function EmptyBrief({ onComposed, title = 'No brief yet today' }: { onComposed: (brief: BriefDoc) => void; title?: string }) {
  const [composing, setComposing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const compose = async () => {
    setComposing(true)
    setError(null)
    try {
      const brief = await generateBrief(null)
      if (!brief) throw new Error('Nothing new has been collected yet, so there is nothing to compose.')
      onComposed(brief)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setComposing(false)
    }
  }

  if (composing) {
    return (
      <div className="r-composing" role="status" aria-live="polite">
        <p className="r-composing__title">Composing your brief</p>
        <div className="r-progress" aria-hidden="true">
          <span />
        </div>
        <p className="r-meta">Spyglass is reading what it collected and picking what matters to you. This usually takes under a minute.</p>
      </div>
    )
  }
  return (
    <>
      <EmptyState
        title={title}
        body="Spyglass composes the brief each morning from what it collected overnight. You can compose one now from what has arrived so far."
        action={
          <Button variant="primary" onClick={compose}>
            Compose now
          </Button>
        }
      />
      {error && (
        <p className="r-error-text" role="alert">
          {error}
        </p>
      )}
    </>
  )
}

/** Placeholder shapes for the masthead and the first stories while the brief loads. */
export function BriefSkeleton() {
  return (
    <div className="r-brief-skeleton" aria-label="Loading the brief" role="status">
      <Skeleton width="38%" height={12} />
      <Skeleton width="72%" height={52} />
      <Skeleton lines={2} height={16} />
      <div style={{ height: 32 }} />
      {[0, 1, 2].map((key) => (
        <div key={key} className="r-brief-skeleton__story">
          <Skeleton width="86%" height={22} />
          <Skeleton lines={2} height={13} />
        </div>
      ))}
    </div>
  )
}
