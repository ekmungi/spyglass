// Tests for the Feed's date headings: which local day an item belongs to, the labels, the counts,
// and the list of rows and headings handed to the page.
import { afterEach, describe, expect, it } from 'vitest'
import type { RadarItem } from '../api/types'
import { dayKey, dayLabel, feedEntries, itemDate } from './dayGroups'

/** A minimal item published at `published` (a Date) and fetched at `fetched`. */
function item(id: number, published: Date | null, fetched: Date = new Date(2026, 10, 12, 8, 0)): RadarItem {
  return { id, headline: `Item ${id}`, published_at: published ? published.toISOString() : null, fetched_at: fetched.toISOString() } as RadarItem
}

const NOON = new Date(2026, 10, 12, 12, 0) // Thursday 12 November 2026, local time

describe('dayKey', () => {
  it('uses the publish date, and the fetch date when there is none (the date the service orders by)', () => {
    expect(dayKey(item(1, new Date(2026, 10, 10, 9, 0), new Date(2026, 10, 12, 9, 0)))).toBe('2026-11-10')
    expect(dayKey(item(2, null, new Date(2026, 10, 11, 9, 0)))).toBe('2026-11-11')
    expect(itemDate(item(3, null, new Date(2026, 10, 11, 9, 0)))?.getDate()).toBe(11)
  })

  it('is null when neither date can be read', () => {
    expect(dayKey({ ...item(1, null), published_at: 'garbage', fetched_at: '' })).toBeNull()
  })

  it('splits at local midnight, not at UTC midnight', () => {
    expect(dayKey(item(1, new Date(2026, 10, 11, 23, 59)))).toBe('2026-11-11')
    expect(dayKey(item(2, new Date(2026, 10, 12, 0, 1)))).toBe('2026-11-12')
  })
})

describe('dayKey in a zone far from UTC', () => {
  // Deleting TZ does not bring the machine's zone back on every platform, so restore it by name.
  const original = Intl.DateTimeFormat().resolvedOptions().timeZone
  afterEach(() => {
    process.env.TZ = original
  })

  it('names the owner’s local day, which is a different day than the UTC one', () => {
    process.env.TZ = 'Etc/GMT-13' // a fixed UTC+13 offset, ahead of the server's day
    const early = new Date('2026-11-11T20:30:00Z') // 09:30 on the 12th at UTC+13
    expect(early.getDate()).toBe(12)
    expect(dayKey({ ...item(1, null), published_at: '2026-11-11T20:30:00Z' })).toBe('2026-11-12')
    // A timestamp with no zone is UTC, as everywhere else in the interface.
    expect(dayKey({ ...item(2, null), published_at: '2026-11-11T20:30:00' })).toBe('2026-11-12')
  })
})

describe('dayLabel', () => {
  it('says Today and Yesterday, then the weekday and date', () => {
    expect(dayLabel('2026-11-12', NOON)).toBe('Today')
    expect(dayLabel('2026-11-11', NOON)).toBe('Yesterday')
    expect(dayLabel('2026-11-10', NOON)).toBe('Tuesday 10 November')
  })

  it('knows Yesterday across a month and a year boundary', () => {
    expect(dayLabel('2026-10-31', new Date(2026, 10, 1, 0, 5))).toBe('Yesterday')
    expect(dayLabel('2025-12-31', new Date(2026, 0, 1, 7, 0))).toBe('Yesterday')
  })

  it('adds the year only for another year', () => {
    expect(dayLabel('2025-12-30', NOON)).toBe('Tuesday 30 December 2025')
  })

  it('moves on at midnight: the same day is Today before and Yesterday after', () => {
    expect(dayLabel('2026-11-12', new Date(2026, 10, 12, 23, 59))).toBe('Today')
    expect(dayLabel('2026-11-12', new Date(2026, 10, 13, 0, 1))).toBe('Yesterday')
  })
})

describe('feedEntries', () => {
  const items = [
    item(1, new Date(2026, 10, 12, 10, 0)),
    item(2, new Date(2026, 10, 12, 7, 0)),
    item(3, new Date(2026, 10, 11, 23, 50)), // before local midnight
    item(4, new Date(2026, 10, 10, 9, 0)),
  ]

  it('puts a heading before each day with the number of that day’s items', () => {
    const entries = feedEntries(items, NOON, false)
    expect(entries.map((entry) => (entry.kind === 'day' ? `${entry.label}:${entry.count}` : entry.item.id))).toEqual([
      'Today:2',
      1,
      2,
      'Yesterday:1',
      3,
      'Tuesday 10 November:1',
      4,
    ])
  })

  it('numbers the rows by their place among the items, never counting the headings', () => {
    const rows = feedEntries(items, NOON, false).flatMap((entry) => (entry.kind === 'item' ? [entry] : []))
    expect(rows.map((row) => [row.item.id, row.index])).toEqual([[1, 0], [2, 1], [3, 2], [4, 3]])
  })

  it('leaves the count off the last day while more pages can still add to it', () => {
    const entries = feedEntries(items, NOON, true)
    const days = entries.flatMap((entry) => (entry.kind === 'day' ? [entry] : []))
    expect(days.map((day) => day.count)).toEqual([2, 1, null])
  })

  it('keeps an item with no readable date in the day above it, and gives a leading one no heading', () => {
    const undated = { ...item(9, null), published_at: null, fetched_at: '' }
    const entries = feedEntries([undated, items[0], undated], NOON, false)
    expect(entries.map((entry) => entry.kind)).toEqual(['item', 'day', 'item', 'item'])
    const day = entries[1]
    expect(day.kind === 'day' && day.count).toBe(2)
  })

  it('gives an empty list no entries', () => {
    expect(feedEntries([], NOON, false)).toEqual([])
  })
})
