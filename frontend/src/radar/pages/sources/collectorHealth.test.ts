// Tests for the alert marks of the Searches and FDA decisions tabs: a failing source marks its tab, a
// source that is only not set up does not, and the Searches mark counts its failing searches.
import { describe, expect, it } from 'vitest'
import type { CollectorRow } from './api'
import { failingSearchesAlert, fdaAlert } from './collectorHealth'

const row = (key: string, over: Partial<CollectorRow> = {}): CollectorRow => ({
  key,
  label: key,
  status: 'ok',
  detail: null,
  lastRun: null,
  newItems: null,
  enabled: null,
  ...over,
})

describe('failingSearchesAlert', () => {
  it('counts only the failing searches, and leaves out the sources other tabs show', () => {
    expect(failingSearchesAlert([row('news'), row('hn', { status: 'error' }), row('rss', { status: 'error' })])).toBe('1 search is failing')
    expect(failingSearchesAlert([row('news', { status: 'error' }), row('hn', { status: 'error' })])).toBe('2 searches are failing')
  })

  it('is empty when no search fails, or one is only not set up', () => {
    expect(failingSearchesAlert([row('news'), row('hn', { status: 'skipped' })])).toBeUndefined()
  })
})

describe('fdaAlert', () => {
  it('marks a failing FDA check, and nothing when it works, is not set up or is absent', () => {
    expect(fdaAlert([row('fda', { status: 'error' })])).toBe('The FDA check is failing')
    expect(fdaAlert([row('fda')])).toBeUndefined()
    expect(fdaAlert([row('fda', { status: 'off' })])).toBeUndefined()
    expect(fdaAlert([row('news')])).toBeUndefined()
  })
})
