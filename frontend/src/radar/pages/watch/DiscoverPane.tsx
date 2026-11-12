// DiscoverPane: the Add dialog's "Find who matters for a topic" step: one input, an honest waiting
// line while the search runs (it can take a minute), and the outcome in plain words.
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/errors'
import { Button, toast } from '../../ui'
import { useElapsed } from '../sources/useElapsed'
import type { DiscoverResult } from './api'
import { describeDiscovery } from './describeDiscovery'

export interface DiscoverPaneProps {
  discover: (topic: string) => Promise<DiscoverResult>
  /** Called after a successful search so the page can reload the register. */
  onDone: () => void
  onBack: () => void
}

/** Topic box plus status line. If the dialog is closed while the search runs, the outcome arrives as a toast. */
export function DiscoverPane({ discover, onDone, onBack }: DiscoverPaneProps) {
  const [topic, setTopic] = useState('')
  const [pending, setPending] = useState(false)
  const seconds = useElapsed(pending)
  const [outcome, setOutcome] = useState<{ text: string; failed: boolean } | null>(null)
  const inputId = useId()
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = topic.trim()
    if (text.length < 2) {
      setOutcome({ text: 'Type a topic of at least two letters.', failed: true })
      return
    }
    setOutcome(null)
    setPending(true)
    try {
      const result = await discover(text)
      const words = describeDiscovery(result)
      onDone()
      if (mounted.current) {
        setOutcome({ text: words, failed: false })
        setTopic('')
      } else {
        toast(words)
      }
    } catch (cause) {
      if (mounted.current) setOutcome({ text: errorMessage(cause), failed: true })
      else toast(errorMessage(cause), { tone: 'error' })
    } finally {
      if (mounted.current) setPending(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <p className="r-meta rw-pane-lead">Name a topic and Spyglass proposes the companies, labs and regulators that matter for it. You accept the ones you want.</p>
      <div className="r-field">
        <label htmlFor={inputId}>Topic</label>
        <input
          id={inputId}
          className="r-input"
          value={topic}
          disabled={pending}
          autoFocus
          placeholder="For example AI in drug discovery"
          onChange={(event) => setTopic(event.target.value)}
        />
      </div>
      <div className="rw-status" role="status" aria-live="polite">
        {pending && (
          <span className="r-meta">
            Searching the web and checking each name. This usually takes 30 to 60 seconds ({seconds}s so far).
          </span>
        )}
        {!pending && outcome && <span className={outcome.failed ? 'r-error-text' : 'r-meta'}>{outcome.text}</span>}
      </div>
      <div className="r-dialog__footer">
        <Button variant="quiet" onClick={onBack} disabled={pending}>
          Back
        </Button>
        <Button variant="primary" type="submit" disabled={pending || !topic.trim()}>
          Find
        </Button>
      </div>
    </form>
  )
}
