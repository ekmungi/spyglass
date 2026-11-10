// Tests for the article-date helpers: relative-then-absolute ages
// and the published-with-collected-fallback card date.
import { describe, expect, it } from 'vitest'
import { cardDate, formatAge } from './dates'

// Fixed "now" so every boundary is deterministic: 2026-07-02T12:00:00Z.
const NOW = new Date('2026-07-02T12:00:00Z')

const minutesAgo = (m: number) => new Date(NOW.getTime() - m * 60_000).toISOString()
const hoursAgo = (h: number) => minutesAgo(h * 60)
const daysAgo = (d: number) => hoursAgo(d * 24)

describe('formatAge', () => {
  it('shows minutes under an hour, flooring, with a 0m floor for the future/just-now', () => {
    expect(formatAge(minutesAgo(0), NOW)).toBe('0m ago')
    expect(formatAge(minutesAgo(38), NOW)).toBe('38m ago')
    expect(formatAge(minutesAgo(59), NOW)).toBe('59m ago')
    // Clock skew can put published_at slightly in the future; never show negative ages.
    expect(formatAge(minutesAgo(-5), NOW)).toBe('0m ago')
  })

  it('shows hours from 60 minutes up to a day', () => {
    expect(formatAge(minutesAgo(60), NOW)).toBe('1h ago')
    expect(formatAge(hoursAgo(5), NOW)).toBe('5h ago')
    expect(formatAge(hoursAgo(23), NOW)).toBe('23h ago')
  })

  it('shows days from 24 hours up to a week', () => {
    expect(formatAge(hoursAgo(24), NOW)).toBe('1d ago')
    expect(formatAge(daysAgo(3), NOW)).toBe('3d ago')
    expect(formatAge(daysAgo(6), NOW)).toBe('6d ago')
  })

  it('shows an absolute date from 7 days, with the year only when it differs', () => {
    expect(formatAge(daysAgo(7), NOW)).toBe('Jun 25')
    expect(formatAge('2026-01-15T09:00:00Z', NOW)).toBe('Jan 15')
    expect(formatAge('2025-12-20T09:00:00Z', NOW)).toBe('Dec 20, 2025')
  })

  it('returns an empty string for unparseable input', () => {
    expect(formatAge('not-a-date', NOW)).toBe('')
  })
})

describe('cardDate', () => {
  it('prefers published_at', () => {
    const d = cardDate({ published_at: '2026-07-01T10:00:00Z', created_at: '2026-07-02T00:00:00Z' })
    expect(d).toEqual({ iso: '2026-07-01T10:00:00Z', collected: false })
  })

  it('falls back to created_at, flagged as collected, when published_at is null', () => {
    const d = cardDate({ published_at: null, created_at: '2026-07-02T00:00:00Z' })
    expect(d).toEqual({ iso: '2026-07-02T00:00:00Z', collected: true })
  })
})
