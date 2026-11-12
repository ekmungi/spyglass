// Sample-mode versions of the Feed's two saved views, matching the service's rules: "Missed" (top
// and notable items of the last 7 days the reader has not opened, saved, filed or sent in, ordered
// by score) and one Watch group's items (the ones the Watch page counts for the group).
import type { RadarItem } from '../api/types'
import { groupWatch } from './catalog'
import type { mockState } from './store'

const WEEK_MS = 7 * 24 * 3600_000

/** Items for the `missed` or `watch_group` query, or null when the query asks for neither. */
export function savedView(state: ReturnType<typeof mockState>, params: URLSearchParams, now = Date.now()): { items: RadarItem[]; byScore: boolean } | null {
  const group = params.get('watch_group')
  const missed = params.get('missed') === 'true'
  if (!missed && group === null) return null
  let items = state.items
  if (group !== null) {
    const found = groupWatch(state.watch, state.items).categories.find((category) => category.name === group)
    const ids = new Set((found?.entities ?? []).flatMap((entity) => (entity.recent ?? []).map((item) => item.id)))
    items = items.filter((item) => ids.has(item.id) && item.tier !== 'out')
  }
  if (!missed) return { items, byScore: false }
  const seen = (item: RadarItem) => item.state.opened || item.state.saved || item.state.from_user || Boolean(item.filed) || item.filing === 'waiting'
  const recent = (item: RadarItem) => now - Date.parse(item.published_at ?? item.fetched_at) <= WEEK_MS
  const kept = items.filter((item) => (item.tier === 'top' || item.tier === 'notable') && recent(item) && !seen(item))
  return { items: [...kept].sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || (b.published_at ?? '').localeCompare(a.published_at ?? '')), byScore: true }
}
