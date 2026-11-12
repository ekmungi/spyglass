// useFeed: the feed list for a set of filters, with cursor paging ("before") for infinite scroll.
// Results per filter set are cached, so returning to the Feed shows the same list at once; the
// first page is then refetched quietly and folded into the list only if it differs.
import { useCallback, useEffect, useRef, useState } from 'react'
import { getFeed } from '../api/client'
import { errorMessage } from '../api/errors'
import type { FeedQuery, RadarItem } from '../api/types'

export interface FeedState {
  items: RadarItem[]
  next: string | null
  total: number
}

const cache = new Map<string, FeedState>()
export const PAGE_SIZE = 50
// Missed is ordered by score, so it has no date cursor and arrives as one page: ask for the most the service allows.
export const MISSED_PAGE_SIZE = 200

/** How many items one request asks for under `query`. */
export function pageSize(query: FeedQuery): number {
  return query.missed ? MISSED_PAGE_SIZE : PAGE_SIZE
}

/** Drop every cached list (tests). */
export function clearFeedCache(): void {
  cache.clear()
}

/** The headline of an item in any list loaded so far, or null (used to name citations in answers). */
export function lookupFeedHeadline(id: number): string | null {
  for (const state of cache.values()) {
    const found = state.items.find((item) => item.id === id)
    if (found) return found.headline
  }
  return null
}

/** Append a page, skipping items already in the list (a cursor can overlap at equal timestamps). */
export function mergePage(current: RadarItem[], page: RadarItem[]): RadarItem[] {
  const seen = new Set(current.map((item) => item.id))
  return [...current, ...page.filter((item) => !seen.has(item.id))]
}

/**
 * Fold a freshly fetched first page into the list already on screen. New and changed items replace
 * the head; everything the reader had already scrolled past (older pages) is kept, so a refresh
 * never shortens the list or moves the reading position. Returns `cached` itself when nothing changed.
 * A first page with nothing after it is the whole list, so it replaces the cached one outright.
 */
export function refreshHead(cached: FeedState, fresh: FeedState): FeedState {
  if (fresh.next === null) return JSON.stringify(fresh) === JSON.stringify(cached) ? cached : fresh
  const freshIds = new Set(fresh.items.map((item) => item.id))
  // The tail starts after the last cached item that the fresh page also contains.
  let lastShared = -1
  cached.items.forEach((item, index) => {
    if (freshIds.has(item.id)) lastShared = index
  })
  const tail = lastShared === -1 ? [] : cached.items.slice(lastShared + 1).filter((item) => !freshIds.has(item.id))
  const merged: FeedState = {
    items: [...fresh.items, ...tail],
    next: tail.length ? cached.next : fresh.next,
    total: fresh.total,
  }
  const unchanged = merged.total === cached.total && merged.next === cached.next && JSON.stringify(merged.items) === JSON.stringify(cached.items)
  return unchanged ? cached : merged
}

interface Snapshot {
  key: string
  state: FeedState | null
  error: string | null
}

/**
 * Load and page the feed for `query`; `active` false (page hidden under the reader) pauses fetching.
 * With `holdOnReturn`, coming back from the reader does not fetch again, so rows the reader just
 * opened stay where they are until the next real load (a reload, or opening the view afresh).
 */
export function useFeed(query: FeedQuery, { active = true, holdOnReturn = false }: { active?: boolean; holdOnReturn?: boolean } = {}) {
  const key = JSON.stringify(query)
  const [snapshot, setSnapshot] = useState<Snapshot>(() => ({ key, state: cache.get(key) ?? null, error: null }))
  const [loadingMore, setLoadingMore] = useState(false)
  const [round, setRound] = useState(0)
  const queryRef = useRef(query)
  const busy = useRef(false)
  const loadedAs = useRef<string | null>(null)

  useEffect(() => {
    queryRef.current = query
  })

  // A different filter set starts from that set's cached list (state adjusted during render).
  let current = snapshot
  if (snapshot.key !== key) {
    current = { key, state: cache.get(key) ?? null, error: null }
    setSnapshot(current)
  }

  useEffect(() => {
    if (!active) return
    if (holdOnReturn && loadedAs.current === `${key}:${round}`) return
    const controller = new AbortController()
    getFeed({ ...queryRef.current, limit: pageSize(queryRef.current) }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return
        loadedAs.current = `${key}:${round}`
        const fresh: FeedState = { items: page.items, next: page.next_before, total: page.total }
        setSnapshot((previous) => {
          if (previous.key !== key) return previous
          const next = previous.state ? refreshHead(previous.state, fresh) : fresh
          cache.set(key, next)
          return next === previous.state && previous.error === null ? previous : { key, state: next, error: null }
        })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setSnapshot((previous) => (previous.key === key ? { ...previous, error: errorMessage(cause) } : previous))
      })
    return () => controller.abort()
  }, [key, round, active, holdOnReturn])

  const nextCursor = current.state?.next ?? null
  const loadMore = useCallback(() => {
    if (!nextCursor || busy.current) return
    busy.current = true
    setLoadingMore(true)
    getFeed({ ...queryRef.current, limit: pageSize(queryRef.current), before: nextCursor })
      .then((page) => {
        setSnapshot((previous) => {
          if (previous.key !== key) return previous
          const merged: FeedState = { items: mergePage(previous.state?.items ?? [], page.items), next: page.next_before, total: page.total }
          cache.set(key, merged)
          return { key, state: merged, error: null }
        })
      })
      .catch((cause: unknown) => setSnapshot((previous) => (previous.key === key ? { ...previous, error: errorMessage(cause) } : previous)))
      .finally(() => {
        busy.current = false
        setLoadingMore(false)
      })
  }, [nextCursor, key])

  const reload = useCallback(() => {
    setSnapshot((previous) => ({ ...previous, error: null }))
    setRound((value) => value + 1)
  }, [])

  return {
    items: current.state?.items ?? [],
    total: current.state?.total ?? 0,
    loading: current.state === null && current.error === null,
    error: current.error,
    hasMore: Boolean(nextCursor),
    loadingMore,
    loadMore,
    reload,
  }
}
