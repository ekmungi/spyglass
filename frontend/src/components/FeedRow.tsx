// Single feed row: inline name edit, health badge, toggle, confirmed delete.
import { useState } from 'react'
import type { FeedData } from '../lib/types'

interface Props {
  feed: FeedData
  onUpdate: (id: number, patch: { enabled?: boolean; name?: string }) => void
  onDelete: (id: number) => void
}

/** Format an ISO timestamp as a locale date+time string, or empty string if null. */
function formatTime(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

/** Map last_fetch_status to a Tailwind color token. */
function badgeClass(status: string | null): string {
  if (status === 'ok') return 'text-accent2'
  if (status === 'error') return 'text-accent'
  return 'text-muted'
}

/** One table row per feed with inline editing, enable/disable, and two-step delete. */
export function FeedRow({ feed, onUpdate, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(feed.name)
  const [confirming, setConfirming] = useState(false)

  function handleNameClick() {
    setDraftName(feed.name)
    setEditing(true)
  }

  function commitRename() {
    setEditing(false)
    if (draftName !== feed.name) {
      onUpdate(feed.id, { name: draftName })
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') commitRename()
    if (e.key === 'Escape') {
      setDraftName(feed.name)
      setEditing(false)
    }
  }

  function handleToggle() {
    onUpdate(feed.id, { enabled: !feed.enabled })
  }

  function handleDeleteClick() {
    setConfirming(true)
  }

  function handleConfirmDelete() {
    setConfirming(false)
    onDelete(feed.id)
  }

  function handleCancelDelete() {
    setConfirming(false)
  }

  const statusLabel = feed.last_fetch_status ?? 'never fetched'
  const fetchTime = formatTime(feed.last_fetch_at)

  return (
    <tr className="border-b border-border" style={{ fontSize: 'var(--font-size-body)' }}>
      {/* Name cell: click to inline-edit */}
      <td className="py-2 pr-4 text-ink">
        {editing ? (
          <input
            type="text"
            className="w-full rounded border border-border bg-canvas px-1 text-ink"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={commitRename}
            onKeyDown={handleKeyDown}
            autoFocus
          />
        ) : (
          <button
            type="button"
            className="cursor-text text-left hover:underline"
            onClick={handleNameClick}
            title="Click to rename"
          >
            {feed.name}
          </button>
        )}
      </td>

      {/* URL */}
      <td className="max-w-[220px] truncate py-2 pr-4 text-muted">{feed.feed_url}</td>

      {/* Health badge */}
      <td className="py-2 pr-4">
        <span className={`font-semibold ${badgeClass(feed.last_fetch_status)}`}>
          {statusLabel}
        </span>
        {fetchTime && (
          <span className="ml-2 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
            {fetchTime}
          </span>
        )}
      </td>

      {/* Item count */}
      <td className="py-2 pr-4 text-muted">{feed.item_count}</td>

      {/* Enable/disable toggle */}
      <td className="py-2 pr-4">
        <input
          type="checkbox"
          checked={feed.enabled}
          onChange={handleToggle}
          aria-label={feed.enabled ? 'Disable feed' : 'Enable feed'}
          className="cursor-pointer"
        />
      </td>

      {/* Delete: two-step confirm */}
      <td className="py-2">
        {confirming ? (
          <span className="flex items-center gap-2">
            <button
              type="button"
              className="text-accent hover:underline"
              onClick={handleConfirmDelete}
              aria-label="Confirm delete"
            >
              Confirm
            </button>
            <button
              type="button"
              className="text-muted hover:underline"
              onClick={handleCancelDelete}
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="text-muted hover:text-accent"
            onClick={handleDeleteClick}
            aria-label={`Delete ${feed.name}`}
          >
            Delete
          </button>
        )}
      </td>
    </tr>
  )
}
