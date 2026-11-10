// Bulk selection bar: session actions plus archive, relevance, category.
import { Columns2, FileText, Archive as ArchiveIcon, Search } from 'lucide-react'
import { RELEVANCE_LEVELS, relevanceColor } from '../../lib/relevance'
import type { CategoryInfo, Relevance } from '../../lib/types'
import { ClaudeIcon } from '../ClaudeIcon'

// The spawned-session actions a selection can trigger.
export type SelectionAction = 'compare' | 'synthesize' | 'deepdive' | 'open'

interface Props {
  count: number
  categories: CategoryInfo[]
  onAction: (action: SelectionAction) => void
  onArchive: () => void
  onBulkRelevance: (relevance: Relevance) => void
  onBulkCategory: (name: string) => void
  onClear: () => void
}

const ACTIONS: { action: SelectionAction; label: string; icon: React.ReactNode }[] = [
  { action: 'compare', label: 'Compare', icon: <Columns2 size={14} /> },
  { action: 'synthesize', label: 'Synthesize', icon: <FileText size={14} /> },
  { action: 'deepdive', label: 'Deep dive', icon: <Search size={14} /> },
  { action: 'open', label: 'Open in Claude', icon: <ClaudeIcon size={14} /> },
]

/** Accent-tinted bar shown only while cards are selected. */
export function SelectionBar({
  count,
  categories,
  onAction,
  onArchive,
  onBulkRelevance,
  onBulkCategory,
  onClear,
}: Props) {
  if (count === 0) {
    return null
  }
  return (
    <div
      className="flex flex-wrap items-center gap-2 border px-3 py-1 text-accent"
      style={{
        fontSize: 'var(--font-size-actions)',
        borderRadius: 'var(--radius-control)',
        background: 'color-mix(in srgb, var(--color-accent) 11%, var(--color-card))',
        borderColor: 'color-mix(in srgb, var(--color-accent) 38%, var(--color-border))',
      }}
    >
      <b>{count} selected</b>
      {ACTIONS.map(({ action, label, icon }) => (
        <button
          key={action}
          type="button"
          className="inline-flex items-center gap-1 text-accent hover:text-ink"
          onClick={() => onAction(action)}
        >
          {icon} {label}
        </button>
      ))}
      <span className="h-4 w-px bg-border" />
      <button
        type="button"
        className="inline-flex items-center gap-1 text-accent hover:text-ink"
        onClick={onArchive}
      >
        <ArchiveIcon size={14} /> Archive
      </button>
      <span
        className="inline-flex gap-0.5 border border-border bg-surface p-0.5"
        style={{ borderRadius: 'var(--radius-control)' }}
        title="Set relevance for selected"
      >
        {RELEVANCE_LEVELS.map((level) => (
          <button
            key={level.value}
            type="button"
            title={`Set relevance: ${level.label}`}
            className="px-2 py-0.5 font-semibold hover:bg-card"
            style={{
              borderRadius: 'var(--radius-control)',
              fontSize: 'var(--font-size-meta)',
              color: relevanceColor(level.value),
            }}
            onClick={() => onBulkRelevance(level.value)}
          >
            {level.value === 'out' ? 'Out' : level.label[0]}
          </button>
        ))}
      </span>
      <select
        aria-label="Set category for selected"
        className="border border-border bg-card px-1.5 py-0.5 text-body"
        style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-meta)' }}
        value=""
        onChange={(event) => {
          if (event.target.value) onBulkCategory(event.target.value)
        }}
      >
        <option value="">Category...</option>
        {[...categories]
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
      </select>
      <button type="button" className="ml-auto text-muted hover:text-ink" onClick={onClear}>
        Clear
      </button>
    </div>
  )
}
