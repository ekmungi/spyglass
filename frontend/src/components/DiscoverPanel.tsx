// DiscoverPanel: shows feed candidates for a URL, supports multi-select add and deep search.
// On reason_code=blocked offers a Google News RSS fallback.
// Opened by AddFeedBar when POST /api/feeds returns 422 not_a_feed.
import { useEffect, useState } from 'react'
import { addFeed, discoverFeeds } from '../lib/api'
import { googleNewsUrl, siteFromUrl } from '../lib/googleNews'
import type { FeedCandidate } from '../lib/types'

interface Props {
  /** The page URL whose feeds we are discovering. */
  url: string
  /** Called after candidates are added to refresh the feed list. */
  onRefresh: () => void
  /** Called when the panel should close (user added feeds or dismissed). */
  onClose: () => void
}

type DepthMode = 'shallow' | 'deep'

/**
 * Discover panel: calls discoverFeeds on mount (shallow), renders candidate checkboxes,
 * provides a "Search deeper" button, and a multi-select "Add selected" action.
 * When reason_code is 'blocked', also offers a Google News RSS subscription form.
 */
export function DiscoverPanel({ url, onRefresh, onClose }: Props) {
  const [candidates, setCandidates] = useState<FeedCandidate[]>([])
  const [reason, setReason] = useState<string | null>(null)
  const [reasonCode, setReasonCode] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Google News affordance state (shown when reason_code === 'blocked').
  const [gnTopic, setGnTopic] = useState('')
  const [gnSite, setGnSite] = useState('')
  const [gnName, setGnName] = useState('')

  /** Run discovery and update state immutably. */
  async function runDiscover(targetDepth: DepthMode) {
    setLoading(true)
    setError(null)
    try {
      const result = await discoverFeeds(url, targetDepth)
      setCandidates(result.candidates)
      setReason(result.reason)
      setReasonCode(result.reason_code ?? null)
      // Prefill the site field from the URL when discovery is blocked.
      if (result.reason_code === 'blocked') {
        setGnSite(siteFromUrl(url))
      }
      // Pre-select all unsubscribed candidates.
      setSelected(
        new Set(
          result.candidates
            .filter((c) => !c.already_subscribed)
            .map((c) => c.feed_url),
        ),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Discovery failed')
    } finally {
      setLoading(false)
    }
  }

  // Fetch shallow candidates when the panel first opens.
  useEffect(() => {
    void runDiscover('shallow')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  function handleToggle(feedUrl: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(feedUrl)) {
        next.delete(feedUrl)
      } else {
        next.add(feedUrl)
      }
      return next
    })
  }

  async function handleSearchDeeper() {
    await runDiscover('deep')
  }

  async function handleAddSelected() {
    if (selected.size === 0) return
    setAdding(true)
    setError(null)
    try {
      await Promise.all([...selected].map((feedUrl) => addFeed(feedUrl)))
      onRefresh()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add feeds')
    } finally {
      setAdding(false)
    }
  }

  /** Submit the Google News subscription form. */
  async function handleGoogleNewsAdd() {
    setAdding(true)
    setError(null)
    try {
      const feedUrl = googleNewsUrl(gnTopic, gnSite)
      await addFeed(feedUrl, gnName || undefined)
      onRefresh()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add Google News feed')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="mt-3 rounded border border-border bg-surface p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium text-text">Feed candidates for {url}</span>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-muted hover:text-text"
          aria-label="Close discovery panel"
        >
          Close
        </button>
      </div>

      {loading && <p className="text-muted">Searching for feeds...</p>}

      {!loading && candidates.length === 0 && (
        <p className="text-muted">
          {reason ? `No feeds found: ${reason}` : 'No feeds found on this page'}
        </p>
      )}

      {!loading && candidates.length > 0 && (
        <ul className="mb-3 space-y-1.5">
          {candidates.map((c) => (
            <li key={c.feed_url} className="flex items-start gap-2">
              <input
                id={`cand-${c.feed_url}`}
                type="checkbox"
                aria-label={c.name}
                checked={selected.has(c.feed_url)}
                disabled={c.already_subscribed}
                onChange={() => handleToggle(c.feed_url)}
                className="mt-0.5 shrink-0"
              />
              <label htmlFor={`cand-${c.feed_url}`} className="flex-1 cursor-pointer">
                <span className="font-medium text-text">{c.name}</span>
                <span className="ml-2 text-xs text-muted">{c.feed_url}</span>
                {c.already_subscribed && (
                  <span className="ml-2 rounded bg-accent/20 px-1.5 py-0.5 text-xs text-accent">
                    Already subscribed
                  </span>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}

      {/* Google News fallback — shown when the site is bot-protected (reason_code=blocked). */}
      {!loading && reasonCode === 'blocked' && (
        <div className="mb-3 mt-2 rounded border border-border bg-surface p-2">
          <p className="mb-2 font-medium text-text">Subscribe via Google News</p>
          <p className="mb-2 text-xs text-muted">
            This site blocks feed discovery. Subscribe to a Google News search instead.
          </p>
          <div className="flex flex-col gap-1.5">
            <input
              type="text"
              value={gnTopic}
              onChange={(e) => setGnTopic(e.target.value)}
              placeholder="Topic (optional)"
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <input
              type="text"
              value={gnSite}
              onChange={(e) => setGnSite(e.target.value)}
              placeholder="Site (e.g. example.com)"
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <input
              type="text"
              value={gnName}
              onChange={(e) => setGnName(e.target.value)}
              placeholder="Display name (optional)"
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <button
              type="button"
              onClick={() => void handleGoogleNewsAdd()}
              disabled={adding || (!gnTopic.trim() && !gnSite.trim())}
              aria-label="Subscribe via Google News"
              className="self-start rounded bg-accent px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              {adding ? 'Adding...' : 'Subscribe via Google News'}
            </button>
          </div>
        </div>
      )}

      {error !== null && (
        <p role="alert" className="mb-2 text-xs text-red-500">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void handleSearchDeeper()}
          disabled={loading}
          className="rounded border border-border px-2 py-1 text-xs text-text hover:bg-surface disabled:opacity-50"
        >
          Search deeper
        </button>

        {candidates.length > 0 && (
          <button
            type="button"
            onClick={() => void handleAddSelected()}
            disabled={adding || selected.size === 0}
            className="rounded bg-accent px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            {adding ? 'Adding...' : 'Add selected'}
          </button>
        )}
      </div>
    </div>
  )
}
