// Recategorize panel: a maintenance + discovery control in Settings.
// The button kicks the background pass (re-file the Unsorted pile into the current categories,
// then cluster the remainder); its proposed new categories are reviewed here -- Accept adds the
// category and files its cards, Discard ignores it. New categories enter the set only on Accept.
import { useEffect, useRef, useState } from 'react'
import * as api from '../lib/api'
import type { RecatCandidate } from '../lib/types'

// How often to re-poll the run status while a pass is in flight.
const POLL_MS = 2000

/** One proposed category: name, size, example titles, and Accept / Discard actions. */
function CandidateRow({
  cand,
  onAccept,
  onDiscard,
}: {
  cand: RecatCandidate
  onAccept: (c: RecatCandidate) => void
  onDiscard: (c: RecatCandidate) => void
}) {
  return (
    <div
      className="flex items-start justify-between gap-3 border border-border bg-canvas px-3 py-2"
      style={{ borderRadius: 'var(--radius-control)' }}
    >
      <div className="min-w-0">
        <div className="font-semibold text-ink">{cand.suggested_name}</div>
        <div className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          {cand.size} articles · {cand.examples.join(' · ')}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <button
          type="button"
          aria-label={`Accept ${cand.suggested_name}`}
          className="border border-border px-2.5 py-1 text-body hover:border-accent"
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={() => onAccept(cand)}
        >
          Accept
        </button>
        <button
          type="button"
          aria-label={`Discard ${cand.suggested_name}`}
          className="text-muted hover:text-accent"
          onClick={() => onDiscard(cand)}
        >
          Discard
        </button>
      </div>
    </div>
  )
}

/** Recategorize control + candidate review list. onAccepted lets the parent refresh its chips. */
export function RecategorizePanel({ onAccepted }: { onAccepted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [candidates, setCandidates] = useState<RecatCandidate[]>([])
  const [message, setMessage] = useState('')
  // Holds the pending poll timer so it can be cancelled on unmount (no leaked interval).
  const timer = useRef<number | undefined>(undefined)

  // Read the latest run; while it is still running, schedule the next poll, otherwise show the
  // candidates. Defined without deps so both mount-resume and the button share one code path.
  const poll = () => {
    api
      .getRecategorize()
      .then((result) => {
        if (result.status === 'running') {
          setBusy(true)
          timer.current = window.setTimeout(poll, POLL_MS)
          return
        }
        setBusy(false)
        setCandidates(result.candidates ?? [])
        if (result.status === 'ok' && (result.candidates ?? []).length === 0) {
          setMessage('No new clusters found — everything fits your current categories.')
        }
      })
      .catch(() => {
        setBusy(false)
        setMessage('recategorize status unavailable')
      })
  }

  // On mount, resume from any prior or in-flight run so a reload keeps its candidates/spinner.
  useEffect(() => {
    poll()
    return () => window.clearTimeout(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = () => {
    // The pass makes one AI call per Unsorted item, so it can take minutes and costs API usage --
    // confirm before kicking.
    if (
      !window.confirm(
        'Recategorize runs the AI classifier over every Unsorted item to file it into your ' +
          'categories. This can take several minutes and uses your OpenRouter API key. Continue?',
      )
    ) {
      return
    }
    setMessage('')
    setCandidates([])
    setBusy(true)
    api
      .recategorize()
      .then(() => poll())
      .catch(() => {
        setBusy(false)
        setMessage('could not start recategorize')
      })
  }

  const accept = (cand: RecatCandidate) => {
    api
      .acceptCandidate(cand.suggested_name, cand.card_ids)
      .then(() => {
        setCandidates((current) => current.filter((c) => c !== cand))
        onAccepted() // new category + counts changed; let the chip list refresh
      })
      .catch(() => setMessage('accept failed'))
  }

  const discard = (cand: RecatCandidate) =>
    setCandidates((current) => current.filter((c) => c !== cand))

  return (
    <div className="mt-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          className="border border-border px-3 py-1 text-body hover:border-accent disabled:opacity-50"
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={run}
          disabled={busy}
        >
          {busy ? 'Recategorizing…' : 'Recategorize'}
        </button>
        <span className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          Uses AI to file the Unsorted pile into your categories and propose new ones — can take a
          few minutes and uses your API key.
        </span>
      </div>
      {candidates.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
            Proposed new categories — accept to add, discard to ignore:
          </p>
          {candidates.map((cand) => (
            <CandidateRow
              key={cand.suggested_name}
              cand={cand}
              onAccept={accept}
              onDiscard={discard}
            />
          ))}
        </div>
      )}
      {message && (
        <span className="mt-2 block text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          {message}
        </span>
      )}
    </div>
  )
}
