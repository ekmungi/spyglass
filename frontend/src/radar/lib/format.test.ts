// Tests for the formatting helpers used across Today, Feed, the reader and the assistant.
import { describe, expect, it } from 'vitest'
import { formatDate, formatDayTitle, hostOf, readMinutes, readingTimeLabel, relativeTime, sentByYou, sourcesLine, stripMarkdown, watchLabel } from './format'

const NOW = new Date('2026-11-12T12:00:00')

describe('dates', () => {
  it('titles a brief day with weekday, day and month', () => {
    expect(formatDayTitle('2026-11-12', NOW)).toBe('Thursday 12 November')
    expect(formatDayTitle('2025-11-12', NOW)).toBe('Wednesday 12 November 2025')
  })

  it('formats timestamps and tolerates bad input', () => {
    expect(formatDate('2026-11-12T08:00:00Z')).toBe('12 Nov 2026')
    expect(formatDate(null)).toBe('')
    expect(formatDate('not a date')).toBe('')
  })

  it('gives short relative times', () => {
    expect(relativeTime(new Date(NOW.getTime() - 20_000).toISOString(), NOW)).toBe('just now')
    expect(relativeTime(new Date(NOW.getTime() - 14 * 60_000).toISOString(), NOW)).toBe('14 min ago')
    expect(relativeTime(new Date(NOW.getTime() - 5 * 3600_000).toISOString(), NOW)).toBe('5 h ago')
    expect(relativeTime(new Date(NOW.getTime() - 30 * 3600_000).toISOString(), NOW)).toBe('yesterday')
    expect(relativeTime(new Date(NOW.getTime() - 3 * 86400_000).toISOString(), NOW)).toBe('3 days ago')
    expect(relativeTime(null, NOW)).toBe('')
  })
})

describe('text helpers', () => {
  it('estimates reading time with a one-minute floor', () => {
    expect(readMinutes(0)).toBe(1)
    expect(readMinutes(1380)).toBe(6)
  })

  it('says "under a minute" instead of "0 min read"', () => {
    expect(readingTimeLabel(0)).toBe('under a minute')
    expect(readingTimeLabel(0.4)).toBe('under a minute')
    expect(readingTimeLabel(Number.NaN)).toBe('under a minute')
    expect(readingTimeLabel(0.5)).toBe('1 min read')
    expect(readingTimeLabel(6)).toBe('6 min read')
    expect(readingTimeLabel(5.6)).toBe('6 min read')
  })

  it('lists two sources and counts the rest', () => {
    const sources = [
      { item_id: 1, name: 'Alpha', url: '' },
      { item_id: 2, name: 'Beta', url: '' },
      { item_id: 3, name: 'Gamma', url: '' },
    ]
    expect(sourcesLine(sources, 5)).toBe('Alpha · Beta · +3')
    expect(sourcesLine(sources.slice(0, 1))).toBe('Alpha')
    expect(sourcesLine([{ item_id: 1, name: 'Alpha', url: '' }, { item_id: 2, name: 'Alpha', url: '' }], 2)).toBe('Alpha · +1')
  })

  it('says how a link the reader sent arrived', () => {
    expect(sentByYou('slack')).toBe('Sent by you from Slack')
    expect(sentByYou('gmail')).toBe('Sent by you by email')
    expect(sentByYou('carrier-pigeon')).toBe('Sent by you via carrier-pigeon')
    expect(sentByYou('browser')).toBe('Sent by you from your browser')
    expect(sentByYou('paste')).toBe('Sent by you as pasted text')
    expect(sentByYou('file')).toBe('Sent by you as a file')
    expect(sentByYou(null)).toBe('Sent by you')
  })

  it('turns markdown into plain text for pasting', () => {
    const markdown = '## Title\n\n**Bold** and *soft* with `code` and [a link](https://example.org).\n\n* one\n* two'
    expect(stripMarkdown(markdown)).toBe('Title\n\nBold and soft with code and a link (https://example.org).\n\n- one\n- two')
  })

  it('extracts a host name', () => {
    expect(hostOf('https://www.example.org/a')).toBe('example.org')
    expect(hostOf('nope')).toBe('')
  })
})

describe('watchLabel', () => {
  it('names the watched organisation with its category', () => {
    expect(watchLabel([{ name: 'Medtronic', category: 'Imaging AI' }])).toBe('Medtronic · Imaging AI')
  })

  it('shows at most two names, de-duplicated, and counts the rest', () => {
    const many = [
      { name: 'A', category: 'X' },
      { name: 'A', category: 'X' },
      { name: 'B', category: 'Y' },
      { name: 'C', category: 'Z' },
    ]
    expect(watchLabel(many)).toBe('A · X, B · Y +1')
  })

  it('copes with a missing category and with nothing to show', () => {
    expect(watchLabel([{ name: 'Solo', category: '' }])).toBe('Solo')
    expect(watchLabel([])).toBeNull()
    expect(watchLabel(undefined)).toBeNull()
    expect(watchLabel([{ name: '  ', category: 'X' }])).toBeNull()
  })
})

describe('timestamps without a zone', () => {
  it('are read as UTC, so a link added 20 seconds ago is "just now" in any time zone', () => {
    const now = new Date('2026-11-12T10:00:30Z')
    expect(relativeTime('2026-11-12T10:00:10', now)).toBe('just now')
    expect(relativeTime('2026-11-12T10:00:10Z', now)).toBe('just now')
    expect(relativeTime('2026-11-12T12:00:10+02:00', now)).toBe('just now')
  })

  it('give the same answer in the formatter used by Sources and the one used by the Feed', async () => {
    const { parseWhen } = await import('../pages/sources/format')
    const { parseTimestamp } = await import('./format')
    expect(parseWhen('2026-11-12T10:00:00')?.toISOString()).toBe('2026-11-12T10:00:00.000Z')
    expect(parseTimestamp('2026-11-12T10:00:00')?.getTime()).toBe(parseWhen('2026-11-12T10:00:00')?.getTime())
    expect(parseTimestamp('nonsense')).toBeNull()
    expect(parseTimestamp(null)).toBeNull()
  })
})
