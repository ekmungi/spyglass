// Header indicator for the linked Claude session: linked or not, and when it last
// called Spyglass, the button that opens a new linked session, and one that ends the link.
import { MessageSquarePlus, Unlink } from 'lucide-react'
import { linkLine } from '../lib/link'
import type { LinkStatus } from '../lib/types'

interface Props {
  status: LinkStatus | null
  onOpen: () => void
  // End the link; the button shows only while a session is linked (or idle).
  onEnd?: () => void
}

export function LinkIndicator({ status, onOpen, onEnd }: Props) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-muted"
      style={{ fontSize: 'var(--font-size-meta)' }}
    >
      <span
        className="size-2 rounded-full"
        style={{ backgroundColor: status?.linked ? 'var(--color-ok)' : 'var(--color-border)' }}
        aria-hidden
      />
      <span>{linkLine(status)}</span>
      {onEnd && (status?.linked || status?.idle) && (
        <button
          type="button"
          className="inline-flex size-7 items-center justify-center border border-border text-muted hover:text-accent hover:bg-card"
          style={{ borderRadius: 'var(--radius-control)' }}
          title="End the link: the Claude session can no longer reach Spyglass (its window stays open)"
          aria-label="End the link to the Claude session"
          onClick={onEnd}
        >
          <Unlink size={14} />
        </button>
      )}
      <button
        type="button"
        className="inline-flex size-7 items-center justify-center border border-border text-accent hover:bg-card"
        style={{ borderRadius: 'var(--radius-control)' }}
        title="Open a linked Claude session"
        aria-label="Open a linked Claude session"
        onClick={onOpen}
      >
        <MessageSquarePlus size={14} />
      </button>
    </span>
  )
}
