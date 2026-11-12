// CollectBar: the one header line of the Sources page: last collection, next brief, and Collect now.
import { useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage } from '../../api/errors'
import { Button, toast } from '../../ui'
import { loadStatus, startCollect, type StatusView } from './api'
import { formatUpcoming, formatWhen } from './format'
import { timing } from './timing'

export interface CollectBarProps {
  status: StatusView | null
  /** Called with each fresh status read while polling. */
  onStatus: (status: StatusView) => void
  /** Called when a collection finishes so the lists can reload. */
  onFinished: () => void
}

type Phase = 'idle' | 'starting' | 'running'

/** Status line plus the Collect now button; handles "already running" and waits for the run to end. */
export function CollectBar({ status, onStatus, onFinished }: CollectBarProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null)
  // The service answers 503 when its scheduler is not running; asking again cannot help.
  const [switchedOff, setSwitchedOff] = useState(false)
  const phaseRef = useRef<Phase>('idle')
  const callbacks = useRef({ onStatus, onFinished })
  const collecting = phase !== 'idle' || status?.running === true

  useEffect(() => {
    callbacks.current = { onStatus, onFinished }
  })

  const go = (next: Phase) => {
    phaseRef.current = next
    setPhase(next)
  }

  useEffect(() => {
    if (!collecting) return
    let cancelled = false
    const timer = setInterval(async () => {
      try {
        const fresh = await loadStatus()
        if (cancelled) return
        callbacks.current.onStatus(fresh)
        if (!fresh.running && phaseRef.current !== 'starting') {
          const wasMine = phaseRef.current === 'running'
          phaseRef.current = 'idle'
          setPhase('idle')
          callbacks.current.onFinished()
          if (wasMine) toast('Collection finished')
        }
      } catch {
        // A single missed status check is not worth interrupting the reader; the next tick tries again.
      }
    }, timing.pollMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [collecting])

  const collect = async () => {
    setNote(null)
    go('starting')
    try {
      const started = await startCollect()
      if (started.background) {
        go('running')
      } else {
        go('idle')
        onFinished()
        setNote({ text: started.found === null ? 'Collection finished.' : `Collection finished: ${started.found} new.`, failed: false })
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        go('running')
        setNote({ text: 'A collection is already running. Waiting for it to finish.', failed: false })
      } else if (cause instanceof ApiError && cause.status === 503) {
        go('idle')
        setSwitchedOff(true)
        setNote({ text: 'Automatic collection is switched off in this copy of Spyglass.', failed: false })
      } else {
        go('idle')
        setNote({ text: errorMessage(cause), failed: true })
      }
    }
  }

  const last = status?.lastCollectAt ? `Last collected ${formatWhen(status.lastCollectAt)}` : 'Nothing has been collected yet'
  const next = status?.nextBriefAt ? `Next brief ${formatUpcoming(status.nextBriefAt)}` : null

  return (
    <div className="rs-collect">
      <div>
        <p className="rs-collect__line">{[last, next].filter(Boolean).join(' · ')}</p>
        <p className="rs-collect__note" role="status" aria-live="polite">
          {collecting ? (
            'Collecting now. This can take a few minutes, and you can leave this page.'
          ) : note ? (
            <span className={note.failed ? 'r-error-text' : undefined}>{note.text}</span>
          ) : null}
        </p>
      </div>
      <Button variant="secondary" disabled={collecting || switchedOff} onClick={() => void collect()}>
        {collecting ? 'Collecting…' : 'Collect now'}
      </Button>
    </div>
  )
}
