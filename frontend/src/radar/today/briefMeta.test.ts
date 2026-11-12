// Tests for the meta line under the date on Today: reading time, story count and collected count.
import { describe, expect, it } from 'vitest'
import type { BriefDoc } from '../api/types'
import { briefMeta } from './briefMeta'

const brief = (overrides: Partial<BriefDoc>): BriefDoc => ({
  day: '2026-11-12',
  generated_at: '2026-11-12T06:30:00Z',
  opening: '',
  quiet: false,
  read_minutes: 6,
  collected: 212,
  filtered_out: 0,
  sections: [{ key: 'top', title: 'Top stories', note: null, stories: [{ id: 'a' }, { id: 'b' }] as never }],
  ...overrides,
})

describe('briefMeta', () => {
  it('joins reading time, stories and the number collected', () => {
    expect(briefMeta(brief({}))).toBe('6 min read · 2 stories from 212 collected')
  })

  it('never says "0 min read": a brief under a minute says so in words', () => {
    expect(briefMeta(brief({ read_minutes: 0, collected: 0 }))).toBe('under a minute · 2 stories')
  })
})
