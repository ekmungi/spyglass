// Feed (#/feed): every item, newest first, under quiet date headings. Search, section chips,
// Saved / From you / Missed / To file, and a Filters menu (kind, show filtered-out). Infinite scroll;
// j/k/Enter/s like Today. A quiet "Related" toggle searches by meaning, and the same list can show the
// items an assistant answer cited, the items close to one item, or one Watch group's week. The
// assistant panel is available here as on Today.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { getProfile } from '../api/client'
import { ITEM_KINDS } from '../api/types'
import { focusComposer, setAssistTarget } from '../assistant/assistStore'
import { openItem } from '../components/openItem'
import { FiledRecently } from '../filing/FiledRecently'
import { FilingPanel } from '../filing/FilingPanel'
import { useFilingOverview } from '../filing/useFilingOverview'
import { DayHeading } from '../feed/DayHeading'
import { feedEntries } from '../feed/dayGroups'
import { feedQuery } from '../feed/feedQuery'
import { FeedRow } from '../feed/FeedRow'
import { FocusChip } from '../feed/FocusChip'
import { useElementHeight } from '../feed/useElementHeight'
import { useFeed } from '../feed/useFeed'
import { useFocusedFeed } from '../feed/useFocusedFeed'
import { useMissedCount } from '../feed/useMissedCount'
import { useDebounced } from '../hooks/useDebounced'
import { useListKeys } from '../hooks/useListKeys'
import { useResource } from '../hooks/useResource'
import { DEFAULT_SECTIONS } from '../lib/sections'
import { navigate } from '../router'
import { useFilingConfiguredState } from '../state/filingConfigured'
import { effectiveFiling, loadFilingCount, useFilingCount, useFilingVersion } from '../state/filingState'
import { toggleSave } from '../state/itemState'
import { Button, Chip, EmptyState, IconAsk, IconFilter, IconSearch, Menu, Skeleton, type MenuItem } from '../ui'
import '../feed/feed.css'

const KIND_LABELS: Record<string, string> = {
  news: 'News',
  release: 'Releases',
  research: 'Research',
  paper: 'Papers',
  post: 'Posts',
  video: 'Videos',
  regulatory: 'Regulatory',
  tool: 'Tools',
  opinion: 'Opinion',
}

/** What an empty list says. The Missed and Watch views are empty when there is nothing to catch up on, which is not a problem to fix. */
function emptyCopy(params: Record<string, string>, anyFilter: boolean): { title: string; body: string } {
  const others = Object.keys(params).filter((key) => key !== 'missed' && key !== 'watch_group').length
  if (params.missed === 'true' && !params.watch_group && !others) {
    return { title: 'Nothing missed', body: 'Every top or notable item from the last 7 days has been opened, saved or filed.' }
  }
  if (params.watch_group && params.missed !== 'true' && !others) {
    return { title: 'Nothing from this group this week', body: 'No item about the names in this group was collected in the last 7 days.' }
  }
  if (anyFilter) return { title: 'Nothing matches these filters', body: 'Try fewer filters or a different search.' }
  return { title: 'Nothing collected yet', body: 'Items appear here as Spyglass collects them from your sources.' }
}

/** Route component for #/feed. */
export function FeedPage({ params, active = true }: { params: Record<string, string>; active?: boolean }) {
  const focus = useFocusedFeed(params, active)
  const focused = focus.mode !== null
  // Filing exists in the Feed only where it is set up; until that is known the Feed shows no filing controls.
  const filingState = useFilingConfiguredState()
  const filingOn = filingState === true
  const query = useMemo(() => feedQuery(params, filingOn), [params, filingOn])
  // Missed lists by score, not by time: no date headings, and an item opened from it stays put until the next load.
  const missedOn = params.missed === 'true'
  const feed = useFeed(query, { active: active && !focused, holdOnReturn: missedOn })
  const missedCount = useMissedCount(active)
  const barRef = useRef<HTMLDivElement>(null)
  const barHeight = useElementHeight(barRef)
  const profile = useResource('profile', getProfile)
  const sections = profile.data?.profile.sections.length ? profile.data.profile.sections : DEFAULT_SECTIONS
  // With "Related" on, the typed text goes to the address as `related` (a search by meaning) instead of `q`.
  const [relatedOn, setRelatedOn] = useState(params.related !== undefined)
  if (params.related !== undefined && !relatedOn) setRelatedOn(true)
  const textKey = relatedOn ? 'related' : 'q'
  const [search, setSearch] = useState(params[textKey] ?? '')
  const debounced = useDebounced(search, 300)
  // A search that changed from outside (a click on Feed in the rail, a link with ?q=) replaces the
  // text in the box; a change this page made itself (the debounced typing below) does not.
  const seenNow = `${textKey}\u0000${params[textKey] ?? ''}`
  const [seen, setSeen] = useState(seenNow)
  if (seenNow !== seen) {
    setSeen(seenNow)
    if ((params[textKey] ?? '') !== debounced.trim()) setSearch(params[textKey] ?? '')
  }
  const [container, setContainer] = useState<HTMLElement | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)

  // The assistant talks about the feed while this page is the one on screen.
  useEffect(() => {
    if (active) setAssistTarget({ kind: 'feed' })
  }, [active])

  /** Change one filter, replacing the history entry so Back leaves the Feed instead of undoing filters. */
  const setParam = useCallback(
    (key: string, value: string | null) => {
      const next = { ...params }
      if (value) next[key] = value
      else delete next[key]
      navigate({ name: 'feed', params: next }, { replace: true })
    },
    [params],
  )

  /** Put the typed text in the address; typing replaces a list taken from an answer or an item. */
  const setTyped = useCallback(
    (value: string | null) => {
      const next = { ...params }
      delete next.cited
      delete next.related_item
      if (value) next[textKey] = value
      else delete next[textKey]
      navigate({ name: 'feed', params: next }, { replace: true })
    },
    [params, textKey],
  )

  useEffect(() => {
    // Write the typed search into the address only once typing has settled.
    if (search.trim() !== debounced.trim()) return
    if ((params[textKey] ?? '') !== debounced.trim()) setTyped(debounced.trim() || null)
  }, [debounced, search, params, textKey, setTyped])

  /** Turn "Related" on or off; the text in the box moves between the plain search and the related search. */
  const toggleRelated = () => {
    const next = { ...params }
    delete next.cited
    delete next.related_item
    if (relatedOn) {
      if (next.related) next.q = next.related
      delete next.related
    } else {
      if (next.q) next.related = next.q
      delete next.q
    }
    setRelatedOn(!relatedOn)
    navigate({ name: 'feed', params: next }, { replace: true })
  }

  /** Leave a list taken from an answer, an item or typed text, back to the whole feed. */
  const clearFocus = () => {
    const next = { ...params }
    delete next.cited
    delete next.related_item
    delete next.related
    setSearch('')
    setRelatedOn(false)
    navigate({ name: 'feed', params: next }, { replace: true })
  }

  // Load the next page when the end of the list comes near.
  const { hasMore, loadMore } = feed
  useEffect(() => {
    const target = sentinel.current
    if (focused || !target || !hasMore || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => entries.some((entry) => entry.isIntersecting) && loadMore(), { rootMargin: '800px 0px' })
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMore, loadMore, focused])

  // The To file filter follows the queue as it changes here: a removed item leaves the list at once.
  const filingCount = useFilingCount()
  const filingVersion = useFilingVersion()
  const toFile = filingOn && params.filing === 'waiting'
  const overview = useFilingOverview(active && toFile && !focused)
  useEffect(() => {
    if (!active || !filingOn) return
    const controller = new AbortController()
    void loadFilingCount(controller.signal)
    return () => controller.abort()
  }, [active, filingOn])
  // A link to the To file view on an install without filing opens the normal Feed and drops the parameter.
  useEffect(() => {
    if (active && filingState === false && params.filing !== undefined) setParam('filing', null)
  }, [active, filingState, params.filing, setParam])
  const listed = focused ? focus.items : feed.items
  // filingVersion is not read inside; it makes the filter run again whenever the queue changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const items = useMemo(() => (toFile && !focused ? listed.filter((item) => effectiveFiling(item.id, item.filing) === 'waiting') : listed), [listed, toFile, focused, filingVersion])
  const onOpen = useCallback((index: number) => items[index] && openItem(items[index].id), [items])
  const onSave = useCallback((index: number) => items[index] && void toggleSave(items[index].id, items[index].state), [items])
  const [selected] = useListKeys({ count: items.length, enabled: active, onOpen, onSave, container })

  const filterItems: MenuItem[] = [
    { id: 'kind-all', label: 'All kinds', checked: !params.kind, onSelect: () => setParam('kind', null) },
    ...ITEM_KINDS.map((kind) => ({ id: `kind-${kind}`, label: KIND_LABELS[kind] ?? kind, checked: params.kind === kind, onSelect: () => setParam('kind', params.kind === kind ? null : kind) })),
    { id: 'tier-all', label: 'Show filtered-out items', checked: params.tier === 'all', onSelect: () => setParam('tier', params.tier === 'all' ? null : 'all') },
    { id: 'filed', label: 'Filed', checked: params.filed === 'true', onSelect: () => setParam('filed', params.filed === 'true' ? null : 'true') },
  ]
  const activeExtra = (params.kind ? 1 : 0) + (params.tier === 'all' ? 1 : 0) + (params.filed === 'true' ? 1 : 0)
  const anyFilter = Object.keys(params).length > 0
  const loading = focused ? focus.loading : feed.loading
  const error = focused ? focus.error : feed.error

  // Date headings only where the list really is in time order.
  const entries = !focused && !missedOn ? feedEntries(items, new Date(), feed.hasMore) : items.map((item, index) => ({ kind: 'item' as const, item, index }))

  const empty = emptyCopy(params, anyFilter)
  let list
  if (loading) {
    list = (
      <div className="r-feed-skeleton" role="status" aria-label="Loading the feed">
        {[0, 1, 2, 3, 4].map((key) => (
          <div key={key}>
            <Skeleton width="80%" height={19} />
            <Skeleton width="95%" height={13} />
            <Skeleton width="40%" height={11} />
          </div>
        ))}
      </div>
    )
  } else if (error && !items.length) {
    list = <EmptyState title="The feed could not be loaded" body={error} action={<Button variant="primary" onClick={focused ? focus.reload : feed.reload}>Try again</Button>} />
  } else if (!items.length && toFile && !focused) {
    // The To file panel above says "Nothing is waiting to be filed"; a second empty message would repeat it.
    list = null
  } else if (!items.length) {
    list = focused ? (
      <EmptyState title="Nothing in your feed is close to that" body="Try different words, or clear this to see the whole feed." action={<Button onClick={clearFocus}>Clear</Button>} />
    ) : (
      <EmptyState
        title={empty.title}
        body={empty.body}
        action={anyFilter ? <Button onClick={() => { setSearch(''); setRelatedOn(false); navigate({ name: 'feed', params: {} }, { replace: true }) }}>Clear filters</Button> : undefined}
      />
    )
  } else {
    list = (
      <>
        <ul className="r-feed" ref={setContainer}>
          {entries.map((entry) =>
            entry.kind === 'day' ? (
              <DayHeading key={`day-${entry.key}`} entry={entry} />
            ) : (
              <FeedRow key={entry.item.id} item={entry.item} index={entry.index} selected={selected === entry.index} />
            ),
          )}
        </ul>
        {!focused && (
          <div ref={sentinel} className="r-feed__end">
            {feed.loadingMore && <Skeleton width="60%" height={14} />}
            {feed.error && <p className="r-error-text">{feed.error}</p>}
            {!feed.hasMore && <p className="r-meta">That is everything{anyFilter ? ' for these filters' : ''}.</p>}
            {feed.hasMore && !feed.loadingMore && (
              <Button variant="quiet" size="sm" onClick={feed.loadMore}>
                Load more
              </Button>
            )}
          </div>
        )}
      </>
    )
  }

  const total = focused ? items.length : feed.total
  const barStyle = barHeight ? ({ '--feed-bar-h': `${barHeight}px` } as CSSProperties) : undefined
  return (
    <div className="r-page r-page--feed" style={barStyle}>
      <h1 className="r-page-title">Feed</h1>
      <p className="r-page-meta">{loading ? ' ' : `${total} ${total === 1 ? 'item' : 'items'}${!focused && params.tier === 'all' ? ', including filtered-out' : ''}`}</p>
      <div className="r-feed-filters" ref={barRef}>
        <div className="r-feed-filters__top">
          <label className="r-feed-search">
            <IconSearch size={16} />
            <span className="r-sr-only">{relatedOn ? 'Describe what to find in the feed' : 'Search the feed'}</span>
            <input
              type="search"
              value={search}
              placeholder={relatedOn ? 'Describe a topic, a paper or an idea' : 'Search titles, summaries and full text'}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <Chip selected={relatedOn} onClick={toggleRelated} title="Find items close in meaning to what you type, not only items with the same words">
            Related
          </Chip>
          <Chip selected={params.saved === 'true'} onClick={() => setParam('saved', params.saved === 'true' ? null : 'true')}>
            Saved
          </Chip>
          <Chip selected={params.from_user === 'true'} onClick={() => setParam('from_user', params.from_user === 'true' ? null : 'true')}>
            From you
          </Chip>
          {filingOn && (
            <Chip selected={toFile} count={filingCount ? filingCount : undefined} onClick={() => setParam('filing', toFile ? null : 'waiting')}>
              To file
            </Chip>
          )}
          <Chip
            selected={missedOn}
            count={missedCount ? missedCount : undefined}
            onClick={() => setParam('missed', missedOn ? null : 'true')}
            title="Top and notable items from the last 7 days that you have not opened, saved or filed"
          >
            Missed
          </Chip>
          <Menu
            label="More filters"
            items={filterItems}
            trigger={
              <Button variant="quiet" size="sm" icon={<IconFilter size={14} />}>
                Filters{activeExtra ? ` (${activeExtra})` : ''}
              </Button>
            }
          />
          {/* The filter bar stays in view while the list scrolls, so this is always within reach. */}
          <Button
            variant="secondary"
            size="sm"
            icon={<IconAsk size={14} />}
            onClick={() => {
              setAssistTarget({ kind: 'feed' })
              focusComposer('feed')
            }}
          >
            Ask your feed
          </Button>
        </div>
        <div className="r-feed-filters__sections" role="group" aria-label="Sections">
          <Chip selected={!params.section} onClick={() => setParam('section', null)}>
            All sections
          </Chip>
          {sections.map((section) => (
            <Chip key={section.key} selected={params.section === section.key} onClick={() => setParam('section', params.section === section.key ? null : section.key)} title={section.description || section.label}>
              {section.label}
            </Chip>
          ))}
        </div>
      </div>
      {focused && focus.chip && <FocusChip text={focus.chip} onClear={clearFocus} />}
      {!focused && params.watch_group && <FocusChip text={`Watch: ${params.watch_group}`} onClear={() => setParam('watch_group', null)} />}
      {toFile && !focused && <FilingPanel count={filingCount} overview={overview.data} error={overview.error} onChanged={overview.reload} />}
      {list}
      {toFile && !focused && <FiledRecently rows={overview.data?.recent ?? []} />}
    </div>
  )
}
