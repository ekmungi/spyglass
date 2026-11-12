// Tests for the feed row: no empty line for items without a "why", a quiet mark for items not
// judged yet, and titles that are always text, never markup.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { RadarItem } from '../api/types'
import { resetItemState } from '../state/itemState'
import { FeedRow } from './FeedRow'

beforeEach(() => resetItemState())
afterEach(cleanup)

function item(over: Partial<RadarItem> = {}): RadarItem {
  return {
    id: 1,
    title: 'A title',
    headline: 'A headline',
    url: 'https://example.org/a',
    source: 'rss',
    origin: 'Example Wire',
    published_at: '2026-11-12T07:00:00',
    fetched_at: '2026-11-12T08:00:00',
    kind: 'news',
    section: 'health',
    section_label: 'Health',
    tier: 'notable',
    score: 70,
    why: 'Matters for your work.',
    key_points: [],
    entities: [],
    signal: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    has_reader: true,
    ...over,
  }
}

const row = (over?: Partial<RadarItem>) =>
  render(
    <ul>
      <FeedRow item={item(over)} index={0} selected={false} />
    </ul>,
  )

describe('FeedRow', () => {
  it('shows the why line when there is one', () => {
    const { container } = row()
    expect(container.querySelector('.r-feedrow__why')?.textContent).toBe('Matters for your work.')
  })

  it('leaves no empty line for an item that was only triaged', () => {
    for (const why of [null, '', '   ']) {
      const { container, unmount } = row({ why })
      expect(container.querySelector('.r-feedrow__why')).toBeNull()
      unmount()
    }
  })

  it('marks an item that has not been judged yet, quietly and in words', () => {
    row({ tier: 'unjudged', why: null, section_label: '' })
    expect(screen.getByText('Not judged yet')).toBeInTheDocument()
    expect(screen.queryByText('Not assessed yet')).toBeNull()
  })

  it('shows entities and stray markup in a title as plain text, never as elements', () => {
    const { container } = row({ headline: '<a href="https://example.org/x" hreflang="en">Q&amp;A: Path tracing</a>', title: 'x' })
    const headline = container.querySelector('.r-feedrow__headline') as HTMLElement
    expect(headline.textContent).toBe('Q&A: Path tracing')
    expect(headline.querySelector('a')).toBeNull()
    expect(headline.children).toHaveLength(0)
  })

  it('does not execute markup smuggled into a title', () => {
    const { container } = row({ headline: 'Hello <img src=x onerror="window.__pwned = true"> <script>window.__pwned = true</script>world' })
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })
})
