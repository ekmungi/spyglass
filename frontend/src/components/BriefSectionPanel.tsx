// Collapsible section panel for the brief reader's tails: the same
// disclosure pattern as the workspace SummaryPanel, but title + default state
// are configurable so References opens and Also noticed starts collapsed.
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'

interface Props {
  // Header label, e.g. "References" or "Also noticed (7)".
  title: string
  // Whether the panel starts expanded.
  defaultOpen: boolean
  // Panel body — rendered only while open (typically a Markdown block).
  children: ReactNode
}

/** Disclosure panel: header button toggles the body; aria-expanded reflects state. */
export function BriefSectionPanel({ title, defaultOpen, children }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className="mt-3.5 border border-border bg-surface"
      style={{ borderRadius: 'var(--radius-control)' }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-label={`${open ? 'Collapse' : 'Expand'} ${title}`}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-3 py-2 font-semibold uppercase tracking-wide text-muted hover:text-accent"
        style={{ fontSize: 'var(--font-size-meta)' }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {title}
      </button>
      {open && <div className="px-3 pb-2.5">{children}</div>}
    </div>
  )
}
