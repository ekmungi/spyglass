// In-dashboard briefing reader: renders the vault note's markdown beautifully.
import { Markdown } from './workspace/Markdown'

interface Props {
  title: string
  markdown: string
  onClose: () => void
}

/** Full-screen overlay showing a finished deep-dive briefing. */
export function BriefingModal({ title, markdown, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-6">
      <div className="max-h-full w-full max-w-3xl overflow-y-auto rounded-xl border border-border bg-card p-8">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-bold text-ink" style={{ fontSize: 'var(--font-size-headline)' }}>
            {title}
          </h2>
          <button
            className="rounded border border-border px-3 py-1 text-muted"
            style={{ fontSize: 'var(--font-size-actions)' }}
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <Markdown
          className="briefing-body text-body"
          style={{ fontSize: 'var(--font-size-body)', lineHeight: 1.6 }}
        >
          {markdown}
        </Markdown>
      </div>
    </div>
  )
}
