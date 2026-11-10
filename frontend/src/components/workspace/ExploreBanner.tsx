// Explore-mode banner: sits above the neighbourhood rows, names the
// seed article, and offers the exit affordance (Escape works too).
import { Telescope, X } from 'lucide-react'

interface Props {
  // Title of the article whose neighbourhood is shown.
  title: string
  // Leave explore mode and restore the normal list.
  onClose: () => void
}

/** One-line banner: "Similar to: <title>" with a close button. */
export function ExploreBanner({ title, onClose }: Props) {
  return (
    <div
      className="mb-2 flex items-center gap-2 border border-accent bg-card px-3 py-2"
      style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
    >
      <Telescope size={14} className="shrink-0 text-accent" aria-hidden />
      <span className="min-w-0 truncate text-body">Similar to: {title}</span>
      <button
        type="button"
        aria-label="Exit explore"
        title="Exit explore (Esc)"
        className="ml-auto inline-flex size-[22px] shrink-0 items-center justify-center border border-border text-muted hover:border-accent hover:text-accent"
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={onClose}
      >
        <X size={13} />
      </button>
    </div>
  )
}
