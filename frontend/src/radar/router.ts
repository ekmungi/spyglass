// Hash router: parses and builds #/routes, notifies subscribers on change, and remembers the
// scroll position of each route so Back returns to the same place. No dependency.
import { useSyncExternalStore } from 'react'

export type Route =
  | { name: 'today'; day?: string }
  | { name: 'feed'; params: Record<string, string> }
  | { name: 'item'; id: number }
  | { name: 'watch' }
  | { name: 'papers' }
  | { name: 'sources' }
  | { name: 'profile' }
  /** `section` scrolls Settings to one group, e.g. "bring-in" for the Send to Spyglass button. */
  | { name: 'settings'; section?: string }
  /** The How to page; `task` opens one task (a stable id such as "add-a-feed"). */
  | { name: 'help'; task?: string }
  /**
   * The small "Add this page to Spyglass?" window opened by the Send to Spyglass button: `token`
   * names a page waiting for confirmation, `error` a fixed reason code from the service.
   */
  | { name: 'import'; token?: string; error?: string }
  /** An address that names no page; shown as "That page does not exist". */
  | { name: 'notfound' }

export type RouteName = Route['name']

const SIMPLE: readonly RouteName[] = ['watch', 'papers', 'sources', 'profile']
const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/
// A staged page's token: 128 random bits as 32 hex characters, exactly as the service makes it.
const TOKEN_PATTERN = /^[0-9a-f]{32}$/
// Settings section names and the service's error codes: short lowercase words.
const WORD_PATTERN = /^[a-z][a-z-]{0,23}$/
// A How to task id such as "find-organisations-for-a-topic": lowercase words joined by hyphens.
const TASK_PATTERN = /^[a-z][a-z-]{0,59}$/

/** The import window's route from its query: only a well-formed token or error code is kept. */
function importRoute(query: URLSearchParams): Route {
  const token = query.get('token') ?? ''
  const error = query.get('error') ?? ''
  if (TOKEN_PATTERN.test(token)) return { name: 'import', token }
  if (WORD_PATTERN.test(error)) return { name: 'import', error }
  return { name: 'import' }
}

/**
 * Parse a location hash ("#/item/12", "#/feed?section=health") into a Route. An empty hash or an
 * in-page anchor is Today; an address that names no page is `notfound`.
 */
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '')
  if (raw !== '' && !raw.startsWith('/')) return { name: 'today' }
  const [pathPart, queryPart = ''] = raw.split('?')
  const segments = pathPart.split('/').filter(Boolean).map(decodeURIComponent)
  const [head, arg] = segments
  if (head === undefined) return { name: 'today' }
  if (head === 'today') return arg === undefined ? { name: 'today' } : DAY_PATTERN.test(arg) ? { name: 'today', day: arg } : { name: 'notfound' }
  if (head === 'item') {
    const id = Number(arg)
    return Number.isInteger(id) && id > 0 ? { name: 'item', id } : { name: 'notfound' }
  }
  if (head === 'feed') {
    const params: Record<string, string> = {}
    new URLSearchParams(queryPart).forEach((value, key) => {
      if (key !== 'mock' && value) params[key] = value
    })
    return { name: 'feed', params }
  }
  if (head === 'help') return arg === undefined ? { name: 'help' } : TASK_PATTERN.test(arg) ? { name: 'help', task: arg } : { name: 'notfound' }
  if (head === 'import') return importRoute(new URLSearchParams(queryPart))
  if (head === 'settings') {
    const section = new URLSearchParams(queryPart).get('section') ?? ''
    return WORD_PATTERN.test(section) ? { name: 'settings', section } : { name: 'settings' }
  }
  if (head && (SIMPLE as readonly string[]).includes(head)) return { name: head as 'watch' | 'papers' | 'sources' | 'profile' }
  return { name: 'notfound' }
}

/** Build the hash for a Route; the inverse of parseHash. */
export function buildHash(route: Route): string {
  switch (route.name) {
    case 'today':
      return route.day ? `#/today/${route.day}` : '#/today'
    case 'item':
      return `#/item/${route.id}`
    case 'feed': {
      const query = new URLSearchParams(Object.entries(route.params).filter(([, value]) => value !== '')).toString()
      return query ? `#/feed?${query}` : '#/feed'
    }
    case 'settings':
      return route.section ? `#/settings?section=${route.section}` : '#/settings'
    case 'help':
      return route.task ? `#/help/${route.task}` : '#/help'
    case 'import':
      if (route.token) return `#/import?token=${route.token}`
      return route.error ? `#/import?error=${route.error}` : '#/import'
    default:
      return `#/${route.name}`
  }
}

/** A stable key for remembering scroll per route (the hash itself, without sample-mode flags). */
export function routeKey(route: Route): string {
  return buildHash(route)
}

/* ---------- scroll memory ---------- */

const scrollPositions = new Map<string, number>()

/**
 * Whether the latest arrival on a page was a Back/Forward step (a traversal of an entry this router
 * made). Only then is a remembered scroll position restored; a click or any forward navigation
 * starts the page at the top.
 */
let arrivedByHistory = false

if (typeof window !== 'undefined') {
  // A real traversal carries the state this router stored; a plain #fragment click carries none.
  window.addEventListener('popstate', (event) => {
    arrivedByHistory = typeof (event.state as { radarIndex?: unknown } | null)?.radarIndex === 'number'
  })
}

/** True when the page now shown was reached with the browser's Back or Forward. */
export function arrivedByHistoryStep(): boolean {
  return arrivedByHistory
}

/** Remember the scroll offset for a route key. */
export function saveScroll(key: string, top: number): void {
  scrollPositions.set(key, Math.max(0, Math.round(top)))
}

/** The remembered scroll offset for a route key (0 when never saved). */
export function getScroll(key: string): number {
  return scrollPositions.get(key) ?? 0
}

/** Forget every remembered scroll position (tests). */
export function clearScrollMemory(): void {
  scrollPositions.clear()
}

/* ---------- navigation ---------- */

/** Current route from window.location. */
export function currentRoute(): Route {
  return parseHash(typeof window === 'undefined' ? '' : window.location.hash)
}

/** What the router keeps in history.state: the entry's depth and, for a reader, where it was opened from. */
interface RadarHistoryState {
  radarIndex?: number
  radarFrom?: string
}

function historyState(): RadarHistoryState {
  return (window.history.state as RadarHistoryState | null) ?? {}
}

/** How many in-app entries precede this one; stored in history.state so the browser Back keeps it right. */
function historyIndex(): number {
  const { radarIndex } = historyState()
  return typeof radarIndex === 'number' ? radarIndex : 0
}

/**
 * The page the reader at the current history entry was opened from (Today, the Feed with its
 * filters, Watch …), or null when unknown. Kept in history.state, so it survives a reload and
 * browser Back/Forward; the rail uses it to highlight the right place while reading.
 */
export function readerOrigin(): Route | null {
  const from = historyState().radarFrom
  if (typeof from !== 'string') return null
  const route = parseHash(from)
  return route.name === 'item' ? null : route
}

/** The origin to record for an entry that shows `route`: only readers carry one. */
function originFor(route: Route): string | undefined {
  if (route.name !== 'item') return undefined
  const here = currentRoute()
  // Moving from one reader to another keeps the page the first one was opened from.
  if (here.name === 'item') return historyState().radarFrom
  return buildHash(here)
}

/** Go to a route; `replace` swaps the current history entry instead of adding one. */
export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  arrivedByHistory = false
  const hash = buildHash(route)
  const url = `${window.location.pathname}${window.location.search}${hash}`
  const from = originFor(route)
  const origin = from === undefined ? {} : { radarFrom: from }
  if (options.replace) {
    window.history.replaceState({ radarIndex: historyIndex(), ...origin }, '', url)
  } else {
    if (window.location.hash === hash) return
    window.history.pushState({ radarIndex: historyIndex() + 1, ...origin }, '', url)
  }
  // pushState/replaceState do not fire hashchange; announce the change ourselves.
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

/** Go back within the app, or to `fallback` when the app was opened directly on this page. */
export function goBack(fallback: Route = { name: 'today' }): void {
  if (historyIndex() > 0) window.history.back()
  else navigate(fallback, { replace: true })
}

/** Subscribe to route changes (used by useRoute). */
function subscribe(callback: () => void): () => void {
  // popstate covers browser Back/Forward between entries made by pushState.
  window.addEventListener('hashchange', callback)
  window.addEventListener('popstate', callback)
  return () => {
    window.removeEventListener('hashchange', callback)
    window.removeEventListener('popstate', callback)
  }
}

// useSyncExternalStore needs a stable snapshot: cache the parsed route per hash string.
let cachedHash: string | null = null
let cachedRoute: Route = { name: 'today' }

/** Snapshot of the current route, re-parsed only when the hash text changes. */
function snapshot(): Route {
  const hash = window.location.hash
  if (hash !== cachedHash) {
    cachedHash = hash
    cachedRoute = parseHash(hash)
  }
  return cachedRoute
}

/** React hook: the current Route, updated on every hash change. */
export function useRoute(): Route {
  return useSyncExternalStore(subscribe, snapshot, () => cachedRoute)
}
