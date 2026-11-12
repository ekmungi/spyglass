// AddFeed: one input that takes a page or feed address. A feed is added at once; a plain page is
// searched for feeds and the reader picks one.
import { useId, useState, type FormEvent } from 'react'
import { ApiError, errorMessage } from '../../api/errors'
import { Button } from '../../ui'
import { addFeed, discoverFeeds, toFeedRow, type FeedCandidate, type FeedRow } from './api'

export interface AddFeedProps {
  onAdded: (feed: FeedRow) => void
}

/** The "Add a feed" form with its status line and the list of feeds found on a page. */
export function AddFeed({ onAdded }: AddFeedProps) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null)
  const [candidates, setCandidates] = useState<FeedCandidate[]>([])
  const inputId = useId()

  const subscribe = async (address: string): Promise<void> => {
    const feed = toFeedRow(await addFeed(address))
    onAdded(feed)
    setNote({ text: `Added ${feed.name}.`, failed: false })
    setCandidates([])
    setUrl('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = url.trim()
    if (!/^https?:\/\//i.test(text)) {
      setNote({ text: 'Enter a full web address starting with http:// or https://.', failed: true })
      return
    }
    setBusy(true)
    setNote(null)
    setCandidates([])
    try {
      await subscribe(text)
    } catch (cause) {
      // A 422 means "this address is not itself a feed": look for feeds on the page before giving up.
      if (cause instanceof ApiError && cause.status === 422) {
        await lookForFeeds(text, cause.message)
      } else {
        setNote({ text: errorMessage(cause), failed: true })
      }
    } finally {
      setBusy(false)
    }
  }

  const lookForFeeds = async (address: string, reason: string) => {
    try {
      const found = await discoverFeeds(address)
      const fresh = found.candidates.filter((candidate) => !candidate.already_subscribed)
      if (fresh.length > 0) {
        setCandidates(fresh)
        setNote({ text: 'That address is a web page. Choose a feed found on it:', failed: false })
      } else if (found.candidates.length > 0) {
        setNote({ text: 'You already follow every feed on that page.', failed: false })
      } else {
        setNote({ text: found.reason ?? reason, failed: true })
      }
    } catch {
      setNote({ text: reason, failed: true })
    }
  }

  const choose = async (candidate: FeedCandidate) => {
    setBusy(true)
    try {
      await subscribe(candidate.feed_url)
    } catch (cause) {
      setNote({ text: errorMessage(cause), failed: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="rs-form" onSubmit={submit} noValidate>
      <label htmlFor={inputId} className="rs-name">
        Add a feed
      </label>
      <p className="rs-sub">Paste the address of a feed, or of a page that has one.</p>
      <div className="rs-form__row">
        <input id={inputId} className="r-input" value={url} placeholder="https://" disabled={busy} onChange={(event) => setUrl(event.target.value)} />
        <Button type="submit" variant="secondary" disabled={busy || !url.trim()}>
          {busy ? 'Checking…' : 'Add feed'}
        </Button>
      </div>
      <p className="rs-form__note" role="status" aria-live="polite">
        {note && <span className={note.failed ? 'r-error-text' : 'r-meta'}>{note.text}</span>}
      </p>
      {candidates.length > 0 && (
        <ul className="rs-candidates">
          {candidates.map((candidate) => (
            <li key={candidate.feed_url}>
              <span>
                {candidate.name} <span className="r-meta">{candidate.feed_url}</span>
              </span>
              <Button size="sm" variant="secondary" disabled={busy} aria-label={`Follow ${candidate.name}`} onClick={() => void choose(candidate)}>
                Follow
              </Button>
            </li>
          ))}
        </ul>
      )}
    </form>
  )
}
