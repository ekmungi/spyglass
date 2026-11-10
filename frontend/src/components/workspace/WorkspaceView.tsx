// Two-pane research workspace: top bar, chips, selection bar, panes.
// Heavy work spawns Claude sessions seeded with spyglass-skill prompts.
import { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../../lib/api'
import { cardDate } from '../../lib/dates'
import { deriveFacets, EMPTY_FILTER, matchesFilter, type FilterState } from '../../lib/filters'
import { displayedRelevance, passesRelevanceFilter, type RelevanceFilter } from '../../lib/relevance'
import type { CardData, CardPatch, CategoryInfo, Relevance, ScoredCard, SearchResult } from '../../lib/types'
import { useActiveFetchJobs } from '../../lib/useActiveFetchJobs'
import { useDebouncedCallback } from '../../lib/useDebouncedCallback'
import { BriefingModal } from '../BriefingModal'
import { FilterBar, type SortBy } from '../FilterBar'
import { CategoryChips } from './CategoryChips'
import { ExploreBanner } from './ExploreBanner'
import { ListPane } from './ListPane'
import { ReaderPane } from './ReaderPane'
import { SelectionBar, type SelectionAction } from './SelectionBar'
import { WorkspaceBar } from './WorkspaceBar'

interface Props {
  cards: CardData[]
  refreshing: boolean
  onRefresh: () => void
  // model pins cheap mechanical passes to Haiku; quality work omits it.
  onOpenClaude: (selectedIds: number[], prompt?: string, model?: string) => void
  onUpdate: (id: number, patch: CardPatch) => void
  onMerge: (id: number, fields: Partial<CardData>) => void
  // Per-item destructive / external actions.
  onDelete: (id: number) => void
  onOpenExternal: (id: number) => void
  // Full card-list reload; called after any thumb or relevance change.
  onReload: () => void
  // Externally requested card to open in the reader (brief card: links);
  // consumed once via onCardRequestHandled so it cannot re-trigger.
  openCardRequest?: number | null
  onCardRequestHandled?: () => void
}

// localStorage key for the persisted list sort, same pattern as spyglass:zoom.
const SORT_STORAGE_KEY = 'spyglass:sort'

/** Read the persisted sort, defaulting to 'collected' (the served order) on anything else. */
function loadSort(): SortBy {
  try {
    return localStorage.getItem(SORT_STORAGE_KEY) === 'published' ? 'published' : 'collected'
  } catch {
    return 'collected'
  }
}

// Coalesce a burst of thumbs/relevance changes into one background reload instead of a blocking
// full-list reload per click. Propagation to neighbours still refreshes.
const RELOAD_DEBOUNCE_MS = 600

// Seeded prompts for the spawn-per-action seam.
const PROMPTS: Record<SelectionAction, string | undefined> = {
  compare: 'Use the spyglass skill: compare the selected cards.',
  synthesize: 'Use the spyglass skill: synthesize the selected cards into a single note.',
  deepdive: 'Use the spyglass skill: run a deep dive on the selected cards.',
  open: undefined,
}

/** The workspace tab: list + reader with selection, search, and categories. */
export function WorkspaceView({ cards, refreshing, onRefresh, onOpenClaude, onUpdate, onMerge, onDelete, onOpenExternal, onReload, openCardRequest, onCardRequestHandled }: Props) {
  // Thumbs merge in place instantly (below); only the corpus-wide propagation refresh is debounced.
  const scheduleReload = useDebouncedCallback(onReload, RELOAD_DEBOUNCE_MS)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER)
  const [showFilter, setShowFilter] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [activeId, setActiveId] = useState<number | null>(null)
  // Keep the service told what is open and ticked, so the linked Claude session can resolve
  // "this one" and "these". Debounced: ticking several boxes sends one update. Not
  // on mount, which would wipe items just sent from the Brief or Inbox, and not after a Claude
  // launch's deselect, which would wipe the items the launch just sent.
  const syncStarted = useRef(false)
  const skipNextSync = useRef(false)
  useEffect(() => {
    if (!syncStarted.current) {
      syncStarted.current = true
      return
    }
    if (skipNextSync.current) {
      skipNextSync.current = false
      return
    }
    const timer = setTimeout(() => {
      api.postSelection([...selected], activeId).catch(() => {})
    }, 300)
    return () => clearTimeout(timer)
  }, [selected, activeId])
  const [reading, setReading] = useState(false)
  // Relevance hide-filter; default 'all'. No longer seeded from settings.
  const [relevanceFilter, setRelevanceFilter] = useState<RelevanceFilter>('all')
  // List sort: collected (served order) or published; persisted across reloads.
  const [sortBy, setSortBy] = useState<SortBy>(loadSort)
  const [activeCat, setActiveCat] = useState('All')
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [briefing, setBriefing] = useState<{ title: string; markdown: string } | null>(null)
  // Explore mode: while set, the list pane shows the seed's scored
  // neighbourhood instead of the filtered list; results null = fetch in flight.
  // Filter/search/sort state is deliberately untouched so exiting restores the view.
  const [explore, setExplore] = useState<{ card: CardData; results: ScoredCard[] | null } | null>(null)
  // Handle on the list pane's own scroll container: filter changes reset it.
  const listScrollRef = useRef<HTMLDivElement>(null)
  // List scroll offset saved on explore entry, restored on exit.
  const exploreScrollRef = useRef(0)
  // Cards with a fetch in flight, polled only while there is one. Reading this
  // on mount is what makes a mid-fetch dashboard reload still show its pending markers.
  const { fetchingIds, refresh: refreshFetchJobs } = useActiveFetchJobs()

  const loadCategories = () => {
    api.getCategories().then(setCategories).catch(() => {})
  }
  useEffect(loadCategories, [])

  // Open a card past any active hiding: clears level/category/facet filters first.
  // Used by external card requests (brief links) and Add page —
  // in both cases the card may be judged low/out, and an empty reader on a
  // deliberate action is worse than resetting the view filters. Explore mode is
  // also dismissed: the request targets the normal feed, and leaving the banner up
  // beside an unrelated article would misrepresent what the list is showing.
  const openCardUnfiltered = (id: number) => {
    setExplore(null)
    setRelevanceFilter('all')
    setActiveCat('All')
    setFilter(EMPTY_FILTER)
    setActiveId(id)
    setReading(true)
  }

  useEffect(() => {
    // Open a card requested from outside (a brief's card: link). This must
    // be an effect: the handled callback updates the PARENT's state (illegal during
    // render), and clearing the request upstream is what guarantees consume-once.
    // The request wins over any active hiding: a brief can reference low/out items
    // (its "Also noticed" list) that a level filter or category chip would hide, and
    // an empty reader on a deliberate click is worse than resetting the view filters.
    if (openCardRequest != null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot request/ack handshake, cannot cascade
      openCardUnfiltered(openCardRequest)
      onCardRequestHandled?.()
    }
  }, [openCardRequest, onCardRequestHandled])

  useEffect(() => {
    // Server FTS with a short debounce; the query handler clears stale results
    // when the box empties, so this effect only ever schedules fetches.
    const term = query.trim()
    if (term === '') {
      return
    }
    const timer = setTimeout(() => {
      api.search(term).then(setResults).catch(() => setResults(null))
    }, 250)
    return () => clearTimeout(timer)
  }, [query])

  const changeQuery = (value: string) => {
    setQuery(value)
    if (value.trim() === '') {
      setResults(null)
    }
  }

  // Any filter change shows a NEW result set, so jump to its top. Keeping the old scroll
  // offset after the list re-derives lands the viewport at an arbitrary depth of a
  // differently-sized list, which reads as the filter not applying. The list owns
  // its scroll container, so reset that too; the window reset covers narrow mode.
  const resetScroll = () => {
    if (listScrollRef.current) {
      listScrollRef.current.scrollTop = 0
    }
    window.scrollTo(0, 0)
  }
  const changeRelevanceFilter = (value: RelevanceFilter) => {
    setRelevanceFilter(value)
    resetScroll()
  }
  const changeFilter = (value: FilterState) => {
    setFilter(value)
    resetScroll()
  }
  const changeCategory = (name: string) => {
    setActiveCat(name)
    resetScroll()
  }
  const changeSortBy = (value: SortBy) => {
    setSortBy(value)
    try {
      localStorage.setItem(SORT_STORAGE_KEY, value)
    } catch {
      // Storage unavailable; the choice stays session-only.
    }
    resetScroll()
  }

  // Facet values only change when the card list does; deriving them per render walks the
  // whole (2000+) corpus for nothing.
  const facets = useMemo(() => deriveFacets(cards), [cards])

  const base: (CardData & { snippet?: string })[] = results ?? cards
  const filtered = base
    .filter((card) => card.state !== 'dismissed')
    .filter((card) => activeCat === 'All' || card.category === activeCat)
    .filter((card) => matchesFilter(card, filter))
    .filter((card) => passesRelevanceFilter(displayedRelevance(card), relevanceFilter))
  // Sort: 'collected' keeps the served order; 'published' re-sorts by article date.
  // FTS results are exempt — their relevance ranking must survive the toggle.
  const visible =
    results === null && sortBy === 'published'
      ? [...filtered].sort((a, b) => Date.parse(cardDate(b).iso) - Date.parse(cardDate(a).iso))
      : filtered
  // Explore mode swaps the list for the seed's neighbourhood; the
  // reader falls back to the full corpus so a card opened before exploring
  // (or the seed itself) stays readable while the neighbourhood loads.
  const listCards: (CardData & { snippet?: string; score?: number })[] = explore
    ? explore.results ?? []
    : visible
  const activeCard =
    listCards.find((card) => card.id === activeId) ??
    (explore ? cards.find((card) => card.id === activeId) ?? null : null)

  const toggle = (id: number, isSelected: boolean) => {
    setSelected((current) => {
      const next = new Set(current)
      if (isSelected) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const createCategory = (name: string) => {
    api.createCategory(name).then(loadCategories).catch(() => {})
  }

  const renameCategory = (oldName: string, newName: string) => {
    api
      .renameCategory(oldName, newName)
      .then(() => {
        loadCategories()
        if (activeCat === oldName) {
          setActiveCat(newName)
        }
      })
      .catch(() => {})
  }

  // Bulk actions deselect when done: the action completed, the selection served
  // its purpose, and a lingering selection invites accidental double-applies.
  // After all updates settle, reload the card list so hide-filter applies immediately.
  const bulkRelevance = (relevance: Relevance) => {
    const ids = [...selected]
    Promise.all(
      ids.map((id) =>
        api.setCardRelevance(id, relevance).then((fields) => onMerge(id, fields)).catch(() => {}),
      ),
    ).then(onReload)
    setSelected(new Set())
  }

  const bulkCategory = (name: string) => {
    for (const id of selected) {
      api.setCardCategory(id, name).then((fields) => onMerge(id, fields)).catch(() => {})
    }
    loadCategories()
    setSelected(new Set())
  }

  const bulkArchive = () => {
    for (const id of selected) {
      onUpdate(id, { state: 'dismissed' })
    }
    setSelected(new Set())
  }

  const readBriefing = (card: CardData) => {
    api
      .getBriefing(card.id)
      .then(({ markdown }) => setBriefing({ title: card.title, markdown }))
      .catch(() => {})
  }

  const sendToClaude = (card: CardData) => {
    const note = card.note ? ` User note: ${card.note}.` : ''
    onOpenClaude(
      [card.id],
      `Use the spyglass skill: work on card ${card.id} ("${card.title}") using its stored full text and highlights.${note}`,
    )
  }

  // Open a card in the reader: shared by ListPane and the SimilarPanel.
  const openCard = (id: number) => {
    setActiveId(id)
    setReading(true)
  }

  // Enter explore mode seeded on a card; re-entering while already
  // exploring chains to the new seed without overwriting the saved scroll.
  const enterExplore = (card: CardData) => {
    setExplore((prev) => {
      if (prev === null) {
        exploreScrollRef.current = listScrollRef.current?.scrollTop ?? 0
      }
      return { card, results: null }
    })
    if (listScrollRef.current) listScrollRef.current.scrollTop = 0
    api
      .getSimilar(card.id, 20)
      .then((results) =>
        // Ignore stale responses: only apply if this seed is still the active one.
        setExplore((prev) => (prev?.card.id === card.id ? { card, results } : prev)),
      )
      .catch(() => setExplore((prev) => (prev?.card.id === card.id ? { card, results: [] } : prev)))
  }

  // Exit explore: the normal list (filters, sort, search) reappears untouched;
  // the saved scroll offset is restored after the list re-renders.
  const exitExplore = () => {
    setExplore(null)
    // Restore after the normal list has re-rendered; fall back to an immediate
    // restore where requestAnimationFrame is unavailable (jsdom).
    const restore = () => {
      if (listScrollRef.current) listScrollRef.current.scrollTop = exploreScrollRef.current
    }
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(restore)
    else restore()
  }

  useEffect(() => {
    // Escape leaves explore mode (mirrors the banner's close button).
    if (explore === null) return
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') exitExplore()
    }
    document.addEventListener('keydown', handle)
    return () => document.removeEventListener('keydown', handle)
  }, [explore])

  // Seed a Claude session to research NEW similar articles on the web and file
  // them back through POST /api/pages.
  const researchCard = (card: CardData) => {
    onOpenClaude(
      [card.id],
      `Use the spyglass skill: research NEW articles similar to card ${card.id} ` +
        `("${card.title}"). Search the web for closely related articles/papers, ` +
        'evaluate each against my interest profile, and file the best finds into ' +
        'Spyglass via POST /api/pages {"url": ...} so they are enriched and judged.',
    )
  }

  // Prune all local state that references the deleted card so phantom rows and
  // stale activeId/reading states cannot survive the parent's cards update.
  const handleDelete = (id: number) => {
    onDelete(id)
    setResults((prev) => (prev ? prev.filter((c) => c.id !== id) : prev))
    setSelected((prev) => {
      if (!prev.has(id)) return prev
      const next = new Set(prev)
      next.delete(id)
      return next
    })
    setActiveId((prev) => (prev === id ? null : prev))
    setReading((prev) => (activeId === id ? false : prev))
  }

  return (
    <>
      {/* Control block: the fixed top of the workspace column (search, filters,
          chips, selection bar). The pane row below scrolls, not this block. */}
      <div className="flex flex-none flex-col gap-2 bg-canvas pb-2">
        <WorkspaceBar
          refreshing={refreshing}
          query={query}
          showFilter={showFilter}
          selectedCount={selected.size}
          onRefresh={onRefresh}
          onQuery={changeQuery}
          onToggleFilter={() => setShowFilter((value) => !value)}
          onOpenClaude={() => {
            onOpenClaude([...selected])
            skipNextSync.current = true
            setSelected(new Set()) // deselect after opening the session (issue #6)
          }}
          onPageAdded={(card) => {
            // Reload so the new card is in the list, then open it in the reader
            // past any hiding filter (a just-judged page can land low/out).
            onReload()
            openCardUnfiltered(card.id)
          }}
        />
        {showFilter && (
          <FilterBar
            facets={facets}
            filter={filter}
            onChange={changeFilter}
            relevanceFilter={relevanceFilter}
            onRelevanceFilter={changeRelevanceFilter}
            sortBy={sortBy}
            onSortBy={changeSortBy}
          />
        )}
        <CategoryChips
          categories={categories}
          active={activeCat}
          onSelect={changeCategory}
          onCreate={createCategory}
          onRename={renameCategory}
        />
        <SelectionBar
          count={selected.size}
          categories={categories}
          onAction={(action) => {
            // Bulk action → deselect when done, matching bulkRelevance/Category/Archive.
            onOpenClaude([...selected], PROMPTS[action])
            skipNextSync.current = true
            setSelected(new Set())
          }}
          onArchive={bulkArchive}
          onBulkRelevance={bulkRelevance}
          onBulkCategory={bulkCategory}
          onClear={() => setSelected(new Set())}
        />
      </div>
      <div className="workspace-panes flex min-h-0 flex-1 items-stretch gap-4 max-md:block max-md:overflow-y-auto">
        <div
          className={`flex min-h-0 shrink-0 grow-0 flex-col ${reading ? 'max-md:hidden' : ''}`}
          style={{ flexBasis: 'var(--list-pane-width)' }}
        >
          {explore && <ExploreBanner title={explore.card.title} onClose={exitExplore} />}
          {explore && explore.results === null && (
            <p className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
              Finding similar articles…
            </p>
          )}
          {explore && explore.results?.length === 0 && (
            <p className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
              No similar articles yet — embeddings may still be building.
            </p>
          )}
          <ListPane
            cards={listCards}
            activeId={activeId}
            selected={selected}
            fetchingIds={fetchingIds}
            scrollRef={listScrollRef}
            onOpen={(id) => {
              openCard(id)
              // Narrow (stacked) mode swaps the list for the reader; jump to
              // the top so the article starts in view however deep the list was.
              if (window.matchMedia?.('(max-width: 768px)').matches) {
                window.scrollTo(0, 0)
              }
            }}
            onToggle={toggle}
            onClaude={(id) => onOpenClaude([id])}
            onOpenExternal={onOpenExternal}
            onArchive={(id) => onUpdate(id, { state: 'dismissed' })}
            onDelete={handleDelete}
            onExplore={(id) => {
              // Seed from whichever list is showing (normal or a neighbourhood,
              // which enables chaining); the corpus covers reader-only cards.
              const card = listCards.find((c) => c.id === id) ?? cards.find((c) => c.id === id)
              if (card) enterExplore(card)
            }}
            onSetFeedback={(id, next) =>
              api
                .setCardFeedback(id, next)
                .then((card) => {
                  // Merge the full returned card in place (instant: dot, relevance, "you set", and a
                  // thumb-down's out-pin land now). The full summary in `card` is cosmetic in the list
                  // (ListPane clamps to 2 lines); the debounced reload re-blends propagation across the
                  // corpus.
                  onMerge(id, card)
                  scheduleReload()
                })
                .catch(() => {})
            }
          />
        </div>
        <div
          // Reader with its own scroll (wide mode, .reader-column CSS): a click
          // deep in the long list shows the article beside it. The activeId key
          // resets the internal scroll when another card opens.
          key={activeId ?? 'none'}
          data-testid="reader-column"
          className={`reader-column min-h-0 min-w-0 flex-1 ${reading ? '' : 'max-md:hidden'}`}
        >
          <ReaderPane
            card={activeCard}
            onBack={() => {
              setActiveId(null)
              setReading(false)
            }}
            categories={categories}
            onUpdate={onUpdate}
            onMerge={onMerge}
            onCreateCategory={createCategory}
            onSend={sendToClaude}
            onReadBriefing={readBriefing}
            onDelete={handleDelete}
            onOpenExternal={onOpenExternal}
            onOpen={openCard}
            onReload={scheduleReload}
            onExplore={enterExplore}
            onResearch={researchCard}
            onFetchStart={refreshFetchJobs}
            onDiscuss={(card, task) => onOpenClaude([card.id], task)}
          />
        </div>
      </div>
      {briefing && (
        <BriefingModal
          title={briefing.title}
          markdown={briefing.markdown}
          onClose={() => setBriefing(null)}
        />
      )}
    </>
  )
}
