// dayGroups: puts date headings ("Today", "Yesterday", "Tuesday 10 November") between the Feed's
// rows when the list is in time order. The day is the owner's local day of the date the service
// orders the list by: the publish date, or the fetch date when an item has none.
import type { RadarItem } from '../api/types'
import { formatDayTitle, parseTimestamp } from '../lib/format'

/** A date heading and how many of the loaded items fall on that day (null while it could still grow). */
export interface DayEntry {
  kind: 'day'
  key: string
  label: string
  count: number | null
}

/** One feed item and its place among the items (headings are not counted). */
export interface ItemEntry {
  kind: 'item'
  item: RadarItem
  index: number
}

export type FeedEntry = DayEntry | ItemEntry

/** The date an item is ordered by in the Feed, or null when neither date can be read. */
export function itemDate(item: RadarItem): Date | null {
  return parseTimestamp(item.published_at) ?? parseTimestamp(item.fetched_at)
}

/** "YYYY-MM-DD" of a date in the viewer's own time zone. */
function localDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** The local calendar day the item belongs to, or null when it has no readable date. */
export function dayKey(item: RadarItem): string | null {
  const date = itemDate(item)
  return date === null ? null : localDay(date)
}

/** "Today", "Yesterday", or the weekday and date ("Tuesday 10 November"; the year when not this one). */
export function dayLabel(key: string, now: Date = new Date()): string {
  if (key === localDay(now)) return 'Today'
  // Built from calendar parts, so a daylight-saving change cannot make "yesterday" two days back.
  if (key === localDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return 'Yesterday'
  return formatDayTitle(key, now)
}

/**
 * The rows of the Feed in time order, with a heading before the first item of each day.
 * An item with no readable date stays in the day above it. `moreBelow` is true while further pages
 * can still add items: the last day's count is then left out, because it would be too small.
 */
export function feedEntries(items: RadarItem[], now: Date, moreBelow: boolean): FeedEntry[] {
  // Runs of rows by day; a run with a null key (undated items before the first dated one) has no heading.
  const runs: { key: string | null; rows: ItemEntry[] }[] = []
  items.forEach((item, index) => {
    const key = dayKey(item)
    const last = runs[runs.length - 1]
    const row: ItemEntry = { kind: 'item', item, index }
    if (last && (key === null || key === last.key)) last.rows.push(row)
    else runs.push({ key, rows: [row] })
  })
  return runs.flatMap((run, position) => {
    if (run.key === null) return run.rows
    const open = moreBelow && position === runs.length - 1
    const heading: DayEntry = { kind: 'day', key: run.key, label: dayLabel(run.key, now), count: open ? null : run.rows.length }
    return [heading, ...run.rows]
  })
}
