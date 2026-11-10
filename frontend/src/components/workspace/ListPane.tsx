// List pane: one row per card with checkbox, relevance dot, title, meta, summary.
// Filtering (hide) is done upstream in WorkspaceView; every card passed here is rendered.
// The pane owns its scroll (.list-column): element-scroll virtualization survives the
// app's CSS zoom, where window-scroll coordinate math does not.
import { ChevronLeft, Loader2, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { RefObject } from 'react'
import { Virtualizer } from 'virtua'
import { cardDate, dateTooltip, formatAge } from '../../lib/dates'
import { displayedRelevance, relevanceColor } from '../../lib/relevance'
import { sourceLabel } from '../../lib/source'
import { ItemCode } from '../ItemCode'
import { stripHtml } from '../../lib/text'
import type { CardData, Feedback } from '../../lib/types'
import { RowActions } from './RowActions'

// Rows may carry an FTS snippet (server search) or a cosine score (explore mode).
type RowCard = CardData & { snippet?: string; score?: number }

interface Props {
  cards: RowCard[]
  activeId: number | null
  selected: Set<number>
  onOpen: (id: number) => void
  onToggle: (id: number, selected: boolean) => void
  // Per-item action callbacks threaded from WorkspaceView.
  onClaude: (id: number) => void
  onOpenExternal: (id: number) => void
  onArchive: (id: number) => void
  onDelete: (id: number) => void
  onSetFeedback: (id: number, next: Feedback) => void
  // Enter explore mode seeded on this card; the action hides when absent.
  onExplore?: (id: number) => void
  // Cards with a fetch in flight, from GET /api/fetch-jobs/active. This is what
  // makes a queued fetch visible anywhere in the app, not only in the reader that started it.
  fetchingIds?: Set<number>
  // The caller's handle on the pane's scroll container (reset to top on filter changes).
  scrollRef?: RefObject<HTMLDivElement | null>
}

/** Render an FTS snippet, turning the [match] markers into accent spans. */
function Snippet({ text }: { text: string }) {
  const parts = text.split(/[[\]]/)
  return (
    <div className="mt-1 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="font-semibold text-accent">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </div>
  )
}

/** One list row. Shows a per-item action cluster on hover (always visible on the active row).
 * The dot color reflects effective_relevance (the blended displayed level). */
function Row({
  card,
  active,
  isSelected,
  fetching,
  onOpen,
  onToggle,
  onClaude,
  onOpenExternal,
  onArchive,
  onDelete,
  onSetFeedback,
  onExplore,
}: {
  card: RowCard
  active: boolean
  isSelected: boolean
  fetching: boolean
  onOpen: (id: number) => void
  onToggle: (id: number, selected: boolean) => void
  onClaude: (id: number) => void
  onOpenExternal: (id: number) => void
  onArchive: (id: number) => void
  onDelete: (id: number) => void
  onSetFeedback: (id: number, next: Feedback) => void
  onExplore?: (id: number) => void
}) {
  const overridden = card.relevance_override || card.category_override
  // The accent label names the real publication; the collector is implicit.
  const meta = [sourceLabel(card).toUpperCase(), card.category, card.tags.join(', ')]
    .filter(Boolean)
    .join(' · ')
  // Article age: published date, collected fallback; full timestamp on hover.
  const date = cardDate(card)
  const age = formatAge(date.iso)
  return (
    // Outer wrapper carries the inter-row gap as PADDING (not margin): the virtualizer
    // measures element height, and margins are excluded from that measurement.
    <div className="pb-2">
    <div
      className={`card-row group relative flex cursor-pointer gap-2.5 border bg-card px-3 py-2.5 ${
        active ? 'is-active border-accent' : 'border-border'
      }`}
      style={{ borderRadius: 'var(--radius-control)' }}
      onClick={() => onOpen(card.id)}
    >
      <input
        type="checkbox"
        className="mt-1 size-3.5 accent-accent"
        checked={isSelected}
        aria-label={`Select ${card.title}`}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onToggle(card.id, event.target.checked)}
      />
      <span
        className="mt-1.5 size-2 shrink-0 rounded-full"
        title={`relevance: ${displayedRelevance(card) ?? 'unjudged'}`}
        style={{ backgroundColor: relevanceColor(displayedRelevance(card)) }}
      />
      <div className="min-w-0 flex-1">
        <div
          className="font-semibold text-ink"
          style={{ fontSize: 'var(--font-size-body)', lineHeight: 1.25 }}
        >
          {card.title}
        </div>
        <div className="mt-1 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
          <span className="font-semibold tracking-wide text-accent">{meta.split(' · ')[0]}</span>
          {meta.includes(' · ') ? ` · ${meta.split(' · ').slice(1).join(' · ')}` : ''}
          {age && (
            <>
              {' · '}
              <span title={dateTooltip(date)}>{age}</span>
            </>
          )}
          {' · '}
          <ItemCode id={card.id} />
          {overridden && (
            <>
              {' · '}
              <span className="text-accent">you set</span>
            </>
          )}
          {card.score !== undefined && (
            <>
              {' · '}
              {/* Cosine similarity to the explore seed, kept muted. */}
              <span title="similarity to the explored article">{card.score.toFixed(2)}</span>
            </>
          )}
          {/* A fetch queued on this card. The whole point of the marker is that
              it shows here, away from the reader that started it — that is what tells the
              user the work outlived the pane they queued it in. */}
          {fetching && (
            <>
              {' · '}
              <Loader2
                size={11}
                className="inline animate-spin align-[-1px] text-accent"
                aria-label="fetching full text"
              />
            </>
          )}
          {/* Persistent at-rest signal: the thumbs themselves live in a hover-only
              action drawer, so a rated row needs its own always-visible marker here. */}
          {card.feedback && (
            <>
              {' · '}
              {card.feedback === 'up' ? (
                <ThumbsUp size={11} fill="currentColor" className="inline align-[-1px] text-ok"
                  aria-label="you liked this" />
              ) : (
                <ThumbsDown size={11} fill="currentColor" className="inline align-[-1px] text-out"
                  aria-label="you disliked this" />
              )}
            </>
          )}
        </div>
        {card.summary && (
          <div className="mt-1 line-clamp-2 text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
            {stripHtml(card.summary)}
          </div>
        )}
        {card.snippet && <Snippet text={card.snippet} />}
      </div>
      {/* Action drawer: absolutely positioned at the row's right edge so it never reserves
          the row's text width. A chevron handle shows on row hover (always on the active
          row); hovering or focusing the drawer slides the actions out over the right edge
          on a solid surface (`.row-action-*` in index.css). The buttons stay mounted
          (CSS-only reveal) so they remain keyboard-reachable and the behavioural tests hold. */}
      <div
        data-testid="row-action-drawer"
        className={`row-action-drawer absolute right-1 top-1/2 flex -translate-y-1/2 items-center transition-opacity focus-within:opacity-100 ${
          active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
        }`}
      >
        <div className="row-action-menu">
          <RowActions
            feedback={card.feedback}
            onFeedback={(next) => onSetFeedback(card.id, next)}
            onClaude={() => onClaude(card.id)}
            onOpenExternal={() => onOpenExternal(card.id)}
            onArchive={() => onArchive(card.id)}
            onDelete={() => onDelete(card.id)}
            onExplore={onExplore ? () => onExplore(card.id) : undefined}
          />
        </div>
        <span
          data-testid="row-action-handle"
          aria-hidden="true"
          className="row-action-handle flex size-[26px] shrink-0 items-center justify-center border border-border bg-card text-muted"
          style={{ borderRadius: 'var(--radius-control)' }}
        >
          <ChevronLeft size={15} />
        </span>
      </div>
    </div>
    </div>
  )
}

/** The scrollable card list; selection is per-row and separate from opening.
 * Filtering (hide) is the responsibility of the caller; every card in the list is rendered.
 * The root div is the scroll container (Virtualizer's default scroller is its parent). */
export function ListPane({
  cards,
  activeId,
  selected,
  onOpen,
  onToggle,
  onClaude,
  onOpenExternal,
  onArchive,
  onDelete,
  onSetFeedback,
  onExplore,
  fetchingIds,
  scrollRef,
}: Props) {
  return (
    <div data-testid="list-pane" ref={scrollRef} className="list-column">
      <Virtualizer>
        {cards.map((card) => (
          <Row
            key={card.id}
            card={card}
            active={card.id === activeId}
            isSelected={selected.has(card.id)}
            fetching={fetchingIds?.has(card.id) ?? false}
            onOpen={onOpen}
            onToggle={onToggle}
            onClaude={onClaude}
            onOpenExternal={onOpenExternal}
            onArchive={onArchive}
            onDelete={onDelete}
            onSetFeedback={onSetFeedback}
            onExplore={onExplore}
          />
        ))}
      </Virtualizer>
    </div>
  )
}
