// Workspace top bar: refresh / FTS search (with inline clear) / facet filter,
// add-page, the relevance threshold, and ONE Claude entry point --
// the spawned session presents the action menu itself.
import { ListFilter, RefreshCw, Search, X } from 'lucide-react'
import type { AddedPage } from '../../lib/types'
import { ClaudeIcon } from '../ClaudeIcon'
import { AddPageControl } from './AddPageControl'

interface Props {
  refreshing: boolean
  query: string
  showFilter: boolean
  selectedCount: number
  onRefresh: () => void
  onQuery: (value: string) => void
  onToggleFilter: () => void
  onOpenClaude: () => void
  // Called with the fetched-and-judged card after Add page succeeds.
  onPageAdded: (card: AddedPage) => void
}

// Controls read in body ink (muted was near-invisible on the light canvas).
const PILL =
  'flex items-center gap-1 border border-border px-2.5 py-1 text-body hover:text-ink'

/** Squared control row above the panes; search is server FTS. */
export function WorkspaceBar({
  refreshing,
  query,
  showFilter,
  selectedCount,
  onRefresh,
  onQuery,
  onToggleFilter,
  onOpenClaude,
  onPageAdded,
}: Props) {
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      style={{ fontSize: 'var(--font-size-actions)' }}
    >
      <button
        type="button"
        aria-label="Refresh"
        title="Fetch new items now"
        className={`${PILL} disabled:opacity-40`}
        style={{ borderRadius: 'var(--radius-control)' }}
        disabled={refreshing}
        onClick={onRefresh}
      >
        {/* Icon-only for density, matching the Claude button; the tooltip
            carries the meaning. */}
        <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
      </button>
      <div
        className="flex items-center gap-1 border border-border px-2.5 py-1"
        style={{ borderRadius: 'var(--radius-control)' }}
      >
        <Search size={14} className="text-muted" />
        <input
          aria-label="Search"
          placeholder="Search full text"
          className="w-32 bg-transparent text-body outline-none"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
        {query !== '' && (
          <button
            type="button"
            aria-label="Clear search"
            title="Clear search"
            className="inline-flex size-4 items-center justify-center rounded-full bg-surface text-muted hover:text-ink"
            onClick={() => onQuery('')}
          >
            <X size={11} />
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="Filter"
        title="Filter"
        className={
          showFilter
            ? 'flex items-center gap-1 border border-accent bg-accent px-2.5 py-1 text-card'
            : PILL
        }
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={onToggleFilter}
      >
        <ListFilter size={14} /> Filter
      </button>
      <AddPageControl onPageAdded={onPageAdded} />
      <span className="ml-auto" />
      <button
        type="button"
        aria-label={`Open Claude Code${selectedCount > 0 ? ` with ${selectedCount} selected` : ''}`}
        title={`Open Claude Code${
          selectedCount > 0 ? ` with ${selectedCount} selected` : ''
        } -- in your linked Claude session`}
        className="inline-flex h-[30px] items-center gap-1.5 border px-2.5 text-accent hover:bg-card"
        style={{
          borderRadius: 'var(--radius-control)',
          borderColor: 'color-mix(in srgb, var(--color-accent) 35%, var(--color-border))',
          background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)',
        }}
        onClick={onOpenClaude}
      >
        <ClaudeIcon size={15} />
        {selectedCount > 0 && (
          <span style={{ fontSize: 'var(--font-size-meta)' }}>{selectedCount}</span>
        )}
      </button>
    </div>
  )
}
