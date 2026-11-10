// Reader pane: header, stored full text, and toolbar.
// Highlights and per-card notes are dormant.
import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import * as api from '../../lib/api'
import { cardDate, dateTooltip, formatAge } from '../../lib/dates'
import { sourceLabel, youtubeVideoId } from '../../lib/source'
import type { CardData, CardPatch, CategoryInfo, Relevance } from '../../lib/types'
import { useCardJobs } from '../../lib/useCardJobs'
import { useFulltextJob } from '../../lib/useFulltextJob'
import { SimilarPanel } from './SimilarPanel'
import { ItemCode } from '../ItemCode'
import { JobBar } from './JobBar'
import { ReaderBody } from './ReaderBody'
import { ReaderToolbar } from './ReaderToolbar'
import { SummaryPanel } from './SummaryPanel'

interface Props {
  card: CardData | null
  onBack: () => void
  categories: CategoryInfo[]
  // PATCH /cards/{id} (state, note); the parent swaps in the updated card.
  onUpdate: (id: number, patch: CardPatch) => void
  // Merge taxonomy PATCH results (relevance/category + override flags) upstream.
  onMerge: (id: number, fields: Partial<CardData>) => void
  onCreateCategory: (name: string) => void
  onSend: (card: CardData) => void
  onReadBriefing?: (card: CardData) => void
  // Per-item destructive / external actions; optional for backward compat.
  onDelete?: (id: number) => void
  onOpenExternal?: (id: number) => void
  // Open another card in the reader (used by the Similar panel).
  onOpen?: (id: number) => void
  // Full card-list reload; called after any thumb or relevance change.
  onReload?: () => void
  // Enter explore mode seeded on this card; the button hides when absent.
  onExplore?: (card: CardData) => void
  // Seed a Claude session to research new similar articles on the web.
  onResearch?: (card: CardData) => void
  // A fetch was just queued, so the list can start polling for its pending
  // markers straight away instead of waiting to notice on its own.
  onFetchStart?: () => void
  // Hand a request about this item to the linked Claude session, e.g. moving its
  // filed note; the Move button hides when absent.
  onDiscuss?: (card: CardData, task: string) => void
}

/** Article reader: placeholder when nothing is open, else the per-card content.
 * Keying by card id remounts the content so its load state resets naturally. */
export function ReaderPane({ card, ...rest }: Props) {
  if (card === null) {
    return (
      <div
        className="border border-dashed border-border bg-card p-9 text-muted"
        style={{ borderRadius: 'var(--radius-card)' }}
      >
        Select an item to read.
      </div>
    )
  }
  return <ReaderContent key={card.id} card={card} {...rest} />
}

/** Header, body, and toolbar for one open card. */
function ReaderContent({
  card,
  onBack,
  categories,
  onUpdate,
  onMerge,
  onCreateCategory,
  onSend,
  onReadBriefing,
  onDelete,
  onOpenExternal,
  onOpen,
  onReload,
  onExplore,
  onResearch,
  onFetchStart,
  onDiscuss,
}: Omit<Props, 'card'> & { card: CardData }) {
  // The list hands over only a short preview summary; seed from it so the
  // panel renders immediately, then replace with the full summary once it arrives.
  const [fullSummary, setFullSummary] = useState<string>(card.summary)

  // Full-text state comes off the server, not this component: the pane is
  // rebuilt from scratch whenever another card is opened, so anything held here about a
  // running fetch would be destroyed with it.
  const { state, fetchNow } = useFulltextJob(card.id, (full) => {
    // A completed job re-enriched the card; the POST no longer carries the result, so the
    // in-place merge happens here from a fresh read.
    onMerge(card.id, full)
    setFullSummary(full.summary)
  })

  // The detailed note and the background jobs that prepare and file it. A finished job
  // changes the item's note, so the list reloads.
  const jobs = useCardJobs(card.id, onReload)

  const startFetch = () => {
    fetchNow()
    onFetchStart?.()
  }

  useEffect(() => {
    let stale = false
    api
      .getCard(card.id)
      .then((full) => {
        if (!stale) setFullSummary(full.summary)
      })
      .catch(() => {})
    return () => {
      stale = true
    }
  }, [card.id])

  return (
    <div
      className="card-shadow relative min-h-[470px] border border-border bg-card px-5 py-4"
      style={{ borderRadius: 'var(--radius-card)' }}
      data-testid="reader-pane"
    >
      <button
        type="button"
        className="mb-3 hidden items-center gap-1 border border-border px-2.5 py-1 text-muted max-md:inline-flex"
        style={{ borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }}
        onClick={onBack}
      >
        <ArrowLeft size={13} /> Back to list
      </button>
      <div
        className="font-semibold uppercase tracking-wider text-accent"
        style={{ fontSize: 'var(--font-size-meta)' }}
      >
        {sourceLabel(card)}
        <span className="ml-2 normal-case tracking-normal text-muted">via {card.source}</span>
        {/* Article age: published date, collected fallback; full timestamp on hover. */}
        <span
          className="ml-2 normal-case tracking-normal text-muted"
          title={dateTooltip(cardDate(card))}
        >
          {formatAge(cardDate(card).iso)}
        </span>
        <span className="ml-2 normal-case tracking-normal">
          <ItemCode id={card.id} />
        </span>
      </div>
      <h2 className="mb-2 mt-1.5 font-bold text-ink" style={{ fontSize: '22px', lineHeight: 1.25 }}>
        {card.title}
      </h2>
      <div
        className="mb-3.5 flex flex-wrap items-center gap-2 text-muted"
        style={{ fontSize: 'var(--font-size-meta)' }}
      >
        <a href={card.url} target="_blank" rel="noreferrer" className="hover:text-accent">
          external link
        </a>
        {state.phase === 'ready' && <span>· full text stored</span>}
      </div>
      <JobBar
        jobs={jobs}
        onRead={() => onReadBriefing?.(card)}
        onMove={
          onDiscuss
            ? (folder) =>
                onDiscuss(card, `Move the detailed note of #${card.id}, now filed in ${folder}, to a better place in my vault. Say where and why before moving it, move it through Obsidian, then call set_item_note.`)
            : undefined
        }
      />
      <SummaryPanel summary={fullSummary} />
      {youtubeVideoId(card.url) && (
        // Privacy-enhanced embed so the video plays in place above the text.
        <div className="mb-4 aspect-video w-full overflow-hidden" style={{ borderRadius: 'var(--radius-control)' }}>
          <iframe
            title="YouTube video player"
            data-testid="youtube-embed"
            width="100%"
            height="100%"
            src={`https://www.youtube-nocookie.com/embed/${youtubeVideoId(card.url)}`}
            allow="accelerometer; encrypted-media; picture-in-picture; web-share"
            allowFullScreen
          />
        </div>
      )}
      <ReaderBody
        card={card}
        state={state}
        marks={[]}
        onMarkClick={() => {}}
        onFetch={startFetch}
      />
      <ReaderToolbar
        card={card}
        categories={categories}
        onArchive={() => onUpdate(card.id, { state: 'dismissed' })}
        onSetRelevance={(relevance: Relevance | null) =>
          api.setCardRelevance(card.id, relevance).then((fields) => {
            onMerge(card.id, fields)
            onReload?.()
          })
        }
        onFeedback={(next) =>
          api.setCardFeedback(card.id, next).then((updated) => {
            onMerge(card.id, updated)
            onReload?.()
          })
        }
        onSetCategory={(name: string) =>
          api.setCardCategory(card.id, name).then((fields) => onMerge(card.id, fields))
        }
        onCreateCategory={onCreateCategory}
        onSend={() => onSend(card)}
        onOpenExternal={onOpenExternal ? () => onOpenExternal(card.id) : undefined}
        onDelete={onDelete ? () => { onDelete(card.id); onBack() } : undefined}
        onExplore={onExplore ? () => onExplore(card) : undefined}
        onResearch={onResearch ? () => onResearch(card) : undefined}
      />
      <SimilarPanel cardId={card.id} onOpen={onOpen} />
    </div>
  )
}
