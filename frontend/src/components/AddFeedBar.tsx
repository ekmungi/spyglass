// AddFeedBar: URL input + optional display name + Add button.
// On not_a_feed (422) opens DiscoverPanel. On other failures shows an inline error.
// Part of the Feeds tab; includes an optional name field.
import { useState } from 'react'
import { NotAFeedError, addFeed } from '../lib/api'
import { DiscoverPanel } from './DiscoverPanel'

interface Props {
  /** Called after a feed is successfully added (or added via discovery) to refresh the list. */
  onRefresh: () => void
}

/**
 * Renders a URL text field, an optional display-name field, and an Add button.
 * Success -> clears the inputs and calls onRefresh.
 * not_a_feed 422 -> opens the DiscoverPanel for that URL.
 * Other errors -> shows an inline error message.
 */
export function AddFeedBar({ onRefresh }: Props) {
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [discoverUrl, setDiscoverUrl] = useState<string | null>(null)

  async function handleAdd() {
    const trimmedUrl = url.trim()
    if (!trimmedUrl) return

    setLoading(true)
    setError(null)

    try {
      // Pass name only when non-empty so the backend treats absence as no override.
      await addFeed(trimmedUrl, name.trim() || undefined)
      setUrl('')
      setName('')
      onRefresh()
    } catch (err) {
      if (err instanceof NotAFeedError) {
        // Not a direct feed URL — open the discovery panel for this page.
        setDiscoverUrl(err.url)
      } else {
        setError(err instanceof Error ? err.message : 'Failed to add feed')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      void handleAdd()
    }
  }

  function handleCloseDiscover() {
    setDiscoverUrl(null)
  }

  return (
    <div className="mb-4">
      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Feed or page URL"
          disabled={loading}
          className="flex-1 rounded border border-border bg-surface px-3 py-1.5 text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Display name (optional)"
          disabled={loading}
          className="w-40 rounded border border-border bg-surface px-3 py-1.5 text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={loading || !url.trim()}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {loading ? 'Adding...' : 'Add'}
        </button>
      </div>

      {error !== null && (
        <p role="alert" className="mt-1 text-xs text-red-500">
          {error}
        </p>
      )}

      {discoverUrl !== null && (
        <DiscoverPanel
          url={discoverUrl}
          onRefresh={onRefresh}
          onClose={handleCloseDiscover}
        />
      )}
    </div>
  )
}
