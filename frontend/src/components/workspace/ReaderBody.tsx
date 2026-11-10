// Reader body states: stored markdown, loading, fetch-on-demand, failure fallback.
import { Download } from 'lucide-react'
import type { Components } from 'react-markdown'
import { rehypeHighlights, type MarkSpec } from '../../lib/highlightMarks'
import type { ReaderState } from '../../lib/readerState'
import { stripHtml } from '../../lib/text'
import type { CardData } from '../../lib/types'
import { Markdown } from './Markdown'

/** Body region: markdown when stored, otherwise the fetch/fallback states.
 * Saved highlights render as persistent clickable marks. */
export function ReaderBody({
  card,
  state,
  marks,
  onMarkClick,
  onFetch,
}: {
  card: CardData
  state: ReaderState
  marks: MarkSpec[]
  onMarkClick: (id: number, event: React.MouseEvent<HTMLElement>) => void
  onFetch: () => void
}) {
  // Clickable mark renderer; the hid travels via the data attribute the plugin set.
  const components: Components = {
    mark: (markProps) => {
      const hid = Number((markProps as Record<string, unknown>)['data-hid'])
      return (
        <mark
          data-hid={hid}
          className="cursor-pointer rounded-[3px] px-px"
          style={{ background: 'color-mix(in srgb, var(--color-accent2) 42%, transparent)', color: 'inherit' }}
          onClick={(event) => onMarkClick(hid, event)}
        >
          {markProps.children}
        </mark>
      )
    },
  }
  if (state.phase === 'loading') {
    return <p className="text-muted">Loading...</p>
  }
  if (state.phase === 'fetching') {
    return <p className="text-muted">Fetching full text...</p>
  }
  if (state.phase === 'ready') {
    return (
      <Markdown
        className="text-body"
        style={{ fontSize: 'var(--font-size-body)', lineHeight: 'var(--leading-body)' }}
        components={components}
        rehypePlugins={[[rehypeHighlights, marks]]}
      >
        {state.markdown}
      </Markdown>
    )
  }
  return (
    <div style={{ fontSize: 'var(--font-size-body)' }}>
      {state.phase === 'failed' ? (
        <p className="mb-3 italic text-muted">
          {state.reason
            ? `The full text could not be fetched — ${state.reason}. Showing the summary.`
            : `The full text could not be fetched (${state.status}); showing the summary.`}
          {state.reason && state.tier && (
            <span className="block not-italic text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
              Reached tier {state.tier}
              {state.detectedType ? ` · detected as ${state.detectedType}` : ''}
            </span>
          )}
        </p>
      ) : (
        <p className="mb-3 italic text-muted">No full text stored yet; showing the summary.</p>
      )}
      <p className="mb-4 text-body">{stripHtml(card.summary)}</p>
      <button
        type="button"
        className="inline-flex items-center gap-1.5 border border-border px-3 py-1.5 text-accent hover:border-accent"
        style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
        onClick={onFetch}
      >
        <Download size={14} /> Fetch full text
      </button>
    </div>
  )
}
