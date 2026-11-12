// The Sources page's only door to the server. The backend's sources, status and feed replies are
// read defensively and turned into the small row types the page uses, so a renamed or missing
// field degrades to "unknown" rather than a blank screen.
import { request } from '../../api/client'
import { requestJson } from './http'

export { captureLink } from '../../api/client'

export type RunState = 'ok' | 'error' | 'skipped' | 'never' | 'off'

export interface FeedRow {
  id: number
  name: string
  url: string
  enabled: boolean
  lastFetchAt: string | null
  status: 'ok' | 'error' | 'never'
  error: string | null
  items: number | null
}

export interface CollectorRow {
  key: string
  label: string
  status: RunState
  /** The last run's one-line outcome or error text, as the server recorded it. */
  detail: string | null
  lastRun: string | null
  newItems: number | null
  enabled: boolean | null
}

export interface SourcesView {
  feeds: FeedRow[]
  collectors: CollectorRow[]
}

export interface StatusView {
  lastCollectAt: string | null
  nextBriefAt: string | null
  /** True while a collection is in progress. */
  running: boolean
}

export interface FeedCandidate {
  feed_url: string
  name: string
  kind: string
  already_subscribed: boolean
}

type Raw = Record<string, unknown>

const str = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null)
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const rec = (value: unknown): Raw => (value && typeof value === 'object' ? (value as Raw) : {})

/** Turn one feed object (either the older feed shape or the shared sample shape) into a FeedRow. */
export function toFeedRow(raw: unknown): FeedRow {
  const feed = rec(raw)
  const status = str(feed.last_fetch_status) ?? str(feed.status)
  return {
    id: num(feed.id) ?? 0,
    name: str(feed.name) ?? str(feed.feed_url) ?? str(feed.url) ?? 'Untitled feed',
    url: str(feed.feed_url) ?? str(feed.url) ?? '',
    enabled: feed.enabled !== false,
    lastFetchAt: str(feed.last_fetch_at) ?? str(feed.last_fetched_at),
    status: status === 'ok' ? 'ok' : status === 'error' ? 'error' : 'never',
    error: str(feed.last_error) ?? str(feed.error),
    items: num(feed.item_count) ?? num(feed.new_items),
  }
}

/** Turn one collector object into a CollectorRow. */
export function toCollectorRow(raw: unknown): CollectorRow {
  const row = rec(raw)
  const key = str(row.key) ?? str(row.name) ?? 'unknown'
  const status = str(row.status)
  return {
    key,
    label: str(row.label) ?? key,
    status: status === 'ok' || status === 'error' || status === 'skipped' || status === 'off' ? status : 'never',
    detail: str(row.detail) ?? str(row.error),
    lastRun: str(row.last_run) ?? str(row.last_run_at),
    newItems: num(row.new_items),
    enabled: typeof row.enabled === 'boolean' ? row.enabled : null,
  }
}

/** The feeds and collectors with their last runs. */
export async function loadSources(signal?: AbortSignal): Promise<SourcesView> {
  const raw = rec(await request<unknown>('GET', '/sources', undefined, signal))
  const feeds = Array.isArray(raw.feeds) ? raw.feeds.map(toFeedRow) : []
  const collectors = Array.isArray(raw.collectors) ? raw.collectors.map(toCollectorRow) : []
  return { feeds, collectors }
}

/** When Spyglass last collected, when the next brief is due, and whether a collection is running. */
export async function loadStatus(signal?: AbortSignal): Promise<StatusView> {
  const raw = rec(await request<unknown>('GET', '/status', undefined, signal))
  return {
    lastCollectAt: str(raw.last_collect_at),
    nextBriefAt: str(raw.next_brief_at),
    running: raw.cycle_running === true || raw.composing === true,
  }
}

export interface CollectStarted {
  /** True when the collection continues in the background and the status must be polled. */
  background: boolean
  /** Items found, when the server finished before answering. */
  found: number | null
}

/** Start a collection now. Rejects with status 409 when one is already running. */
export async function startCollect(): Promise<CollectStarted> {
  const raw = rec(await request<unknown>('POST', '/collect', {}))
  return { background: raw.started === true, found: num(raw.new) }
}

/** Subscribe to a feed address; rejects with a plain reason when the address is not a feed. */
export const addFeed = (url: string) => requestJson<Raw>('POST', '/api/feeds', { url })

/** Look for feeds on a web page. */
export const discoverFeeds = (url: string) =>
  requestJson<{ candidates: FeedCandidate[]; reason: string | null }>('POST', '/api/feeds/discover', { url, depth: 0 })

/** Switch a feed on or off. */
export const setFeedEnabled = (id: number, enabled: boolean) => requestJson<Raw>('PATCH', `/api/feeds/${id}`, { enabled })

/** Delete a feed and the items it collected. */
export const removeFeed = (id: number) => requestJson<Raw>('DELETE', `/api/feeds/${id}`)
