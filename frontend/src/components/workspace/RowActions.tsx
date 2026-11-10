// Per-item action cluster: feedback thumbs, explore, Claude, browser, archive, delete.
// Used inside ListPane rows; click propagation stops at the container div.
import { Archive, Globe, Telescope, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Feedback } from '../../lib/types'
import { ClaudeIcon } from '../ClaudeIcon'
import { ThumbsControl } from './ThumbsControl'

// Props for the per-item actions; delete requires user confirmation.
interface Props {
  feedback: Feedback                   // current thumbs state
  onFeedback: (next: Feedback) => void // tap sets; re-tapping the active thumb clears (null)
  onClaude: () => void       // open this item as context in Claude
  onOpenExternal: () => void // open the item's link in the default browser
  onArchive: () => void      // soft archive (dismissed)
  onDelete: () => void       // permanent delete (needs confirm)
  onExplore?: () => void     // enter explore mode seeded on this item
}

// Icon button class matching the reader toolbar's ICON style.
const BTN =
  'inline-flex size-[26px] items-center justify-center border border-border text-body hover:border-accent hover:text-accent'

/** Compact right-aligned action cluster for one list row.
 * Propagation stops at the wrapper so row clicks are never triggered.
 * Delete is two-step: first click shows a confirm button; second fires onDelete.
 * Escape key or Cancel button resets the confirming state. */
export function RowActions({ feedback, onFeedback, onClaude, onOpenExternal, onArchive, onDelete, onExplore }: Props) {
  const [confirming, setConfirming] = useState(false)

  // Escape key cancels the pending delete confirmation.
  useEffect(() => {
    if (!confirming) return
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfirming(false)
    }
    document.addEventListener('keydown', handle)
    return () => document.removeEventListener('keydown', handle)
  }, [confirming])

  return (
    <div
      className="flex shrink-0 items-center gap-1"
      onClick={(event) => event.stopPropagation()}
    >
      <ThumbsControl feedback={feedback} onFeedback={onFeedback} btnClass={BTN} iconSize={14} />
      {onExplore && (
        <button
          type="button"
          aria-label="Explore similar"
          title="Explore similar articles in the workspace"
          className={BTN}
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={onExplore}
        >
          <Telescope size={14} />
        </button>
      )}
      <button
        type="button"
        aria-label="Open in Claude"
        title="Open in Claude"
        className={BTN}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={onClaude}
      >
        <ClaudeIcon size={14} />
      </button>
      <button
        type="button"
        aria-label="Open in browser"
        title="Open in browser"
        className={BTN}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={onOpenExternal}
      >
        <Globe size={14} />
      </button>
      <button
        type="button"
        aria-label="Archive"
        title="Archive"
        className={BTN}
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={onArchive}
      >
        <Archive size={14} />
      </button>
      {confirming ? (
        <>
          <button
            type="button"
            aria-label="Confirm delete"
            title="Confirm delete"
            className="inline-flex items-center border border-red-500 px-1.5 py-0.5 text-red-500 hover:bg-red-50"
            style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
            onClick={onDelete}
          >
            Delete?
          </button>
          <button
            type="button"
            aria-label="Cancel delete"
            title="Cancel delete"
            className="inline-flex items-center border border-border px-1.5 py-0.5 text-muted hover:border-accent"
            style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          aria-label="Delete"
          title="Delete"
          className={BTN}
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={() => setConfirming(true)}
        >
          <Trash2 size={14} />
        </button>
      )}
    </div>
  )
}
