// "Add page" control for the workspace bar: a collapsed affordance
// that expands into an inline URL input (AddFeedBar interaction pattern).
// POST /api/pages fetches + enriches + judges the page — the in-flight label says so.
import { Loader2, Plus, X } from 'lucide-react'
import { useState } from 'react'
import * as api from '../../lib/api'
import type { AddedPage } from '../../lib/types'

interface Props {
  // Receives the created (or already-existing) card so the caller can reload
  // the list and open it in the reader.
  onPageAdded: (card: AddedPage) => void
}

// Same pill styling as the sibling WorkspaceBar controls.
const PILL =
  'flex items-center gap-1 border border-border px-2.5 py-1 text-body hover:text-ink'

/** Collapsed: a "+ Add page" pill. Expanded: URL input + Add + cancel.
 * Enter submits, Escape cancels; failures show an honest inline error and keep
 * the input so the URL can be corrected. Success collapses and hands the card up. */
export function AddPageControl({ onPageAdded }: Props) {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setOpen(false)
    setUrl('')
    setError(null)
  }

  const add = () => {
    const trimmed = url.trim()
    if (!trimmed || loading) return
    setLoading(true)
    setError(null)
    api
      .addPage(trimmed)
      .then((card) => {
        // created and exists land the same way: open the card.
        reset()
        onPageAdded(card)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') add()
    if (event.key === 'Escape' && !loading) reset()
  }

  if (!open) {
    return (
      <button
        type="button"
        aria-label="Add page"
        title="Add a single web page by URL"
        className={PILL}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={() => setOpen(true)}
      >
        <Plus size={14} /> Add page
      </button>
    )
  }

  return (
    <span className="flex items-center gap-1.5">
      <span
        className="flex items-center gap-1 border border-border px-2.5 py-1"
        style={{ borderRadius: 'var(--radius-control)' }}
      >
        <input
          aria-label="Page URL"
          placeholder="Page URL"
          className="w-52 bg-transparent text-body outline-none"
          value={url}
          disabled={loading}
          autoFocus
          onChange={(event) => {
            setUrl(event.target.value)
            setError(null)
          }}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          aria-label="Cancel add page"
          title="Cancel"
          className="inline-flex size-4 items-center justify-center rounded-full bg-surface text-muted hover:text-ink disabled:opacity-40"
          disabled={loading}
          onClick={reset}
        >
          <X size={11} />
        </button>
      </span>
      <button
        type="button"
        className={`${PILL} disabled:opacity-40`}
        style={{ borderRadius: 'var(--radius-control)' }}
        disabled={loading || !url.trim()}
        onClick={add}
      >
        {loading ? (
          <>
            <Loader2 size={13} className="animate-spin" /> Adding &amp; judging…
          </>
        ) : (
          'Add'
        )}
      </button>
      {error !== null && (
        <span role="alert" className="text-accent" style={{ fontSize: 'var(--font-size-meta)' }}>
          {error}
        </span>
      )}
    </span>
  )
}
