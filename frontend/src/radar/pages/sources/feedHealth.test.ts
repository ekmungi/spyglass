// Tests for the feed health wording: which feeds fail, the alert on the Feeds tab, and the one-line
// count that stands in for the working feeds.
import { describe, expect, it } from 'vitest'
import type { FeedRow } from './api'
import { failingAlert, otherFeedsSummary, placeFeeds, splitFeeds } from './feedHealth'

let next = 1
const feed = (over: Partial<FeedRow> = {}): FeedRow => ({
  id: next++,
  name: 'F',
  url: '',
  enabled: true,
  lastFetchAt: null,
  status: 'ok',
  error: null,
  items: null,
  ...over,
})
const failing = () => feed({ status: 'error', error: 'x' })
const off = () => feed({ enabled: false })
const waiting = () => feed({ status: 'never' })

describe('splitFeeds', () => {
  it('puts the feeds that work apart from every other state', () => {
    const [ok, a, b, c] = [feed(), failing(), off(), waiting()]
    const { working, others } = splitFeeds([a, ok, b, c])
    expect(working).toEqual([ok])
    expect(others).toEqual([a, b, c])
  })
})

describe('placeFeeds', () => {
  it('keeps a feed the reader changed in the list it was in, and places the rest by their state', () => {
    const [ok, nowOn, nowOff] = [feed(), feed(), off()]
    const kept = new Map([
      [nowOn.id, 'others' as const],
      [nowOff.id, 'working' as const],
    ])
    const { working, others } = placeFeeds([ok, nowOn, nowOff], kept)
    expect(working).toEqual([ok, nowOff])
    expect(others).toEqual([nowOn])
  })
})

describe('failingAlert', () => {
  it('is empty when no feed fails, and a switched-off feed does not count', () => {
    expect(failingAlert([feed(), off(), waiting()])).toBeUndefined()
    expect(failingAlert([])).toBeUndefined()
  })

  it('counts the failing feeds in a sentence', () => {
    expect(failingAlert([feed(), failing()])).toBe('1 feed is failing')
    expect(failingAlert([failing(), failing(), off()])).toBe('2 feeds are failing')
  })
})

describe('otherFeedsSummary', () => {
  it('counts each state that is not working, switched off first', () => {
    const others = [failing(), off(), off(), off(), waiting()]
    expect(otherFeedsSummary(others)).toBe('3 switched off, 1 not fetched yet, 1 failing')
  })

  it('is empty when every feed works', () => {
    expect(otherFeedsSummary([])).toBe('')
  })
})
