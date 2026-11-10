// Collapsible "Summary" panel for the reader: shows the enriched summary as
// rich Markdown, open by default, tucked away on demand. No summary -> renders nothing.
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { stripHtml } from '../../lib/text'
import { Markdown } from './Markdown'

interface SummaryPanelProps {
  // Markdown summary text; empty -> the panel renders nothing (same guard as before).
  summary: string
}

/** Disclosure panel surfacing the article summary at the top of the reader.
 * Starts expanded; the header button toggles it (aria-expanded reflects state).
 * The body renders via the shared Markdown component so bold/lists/links show as rich text. */
export function SummaryPanel({ summary }: SummaryPanelProps) {
  const [open, setOpen] = useState(true)
  if (!summary) return null
  // Enriched summaries are clean Markdown; un-enriched RSS blurbs carry HTML markup.
  // react-markdown renders raw HTML as literal tag text, so HTML summaries are stripped
  // to plain text instead. stripHtml collapses newlines, so it must NOT touch Markdown.
  const isHtml = /<\/?[a-z][a-z0-9]*[\s/>]/i.test(summary)
  return (
    <div
      className="mb-3.5 border border-border bg-surface"
      style={{ borderRadius: 'var(--radius-control)' }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-label={open ? 'Collapse summary' : 'Expand summary'}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-3 py-2 font-semibold uppercase tracking-wide text-muted hover:text-accent"
        style={{ fontSize: 'var(--font-size-meta)' }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        Summary
      </button>
      {open && (
        <div className="px-3 pb-2.5">
          {isHtml ? (
            <p className="text-body" style={{ fontSize: 'var(--font-size-meta)' }}>
              {stripHtml(summary)}
            </p>
          ) : (
            <Markdown className="text-body" style={{ fontSize: 'var(--font-size-meta)' }}>
              {summary}
            </Markdown>
          )}
        </div>
      )}
    </div>
  )
}
