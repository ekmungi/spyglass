// Tests for FeedsTab: empty state and feed list rendering.
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FeedData } from '../lib/types'
import { FeedsTab } from './FeedsTab'

vi.mock('../lib/api')

const feeds: FeedData[] = [
  {
    id: 1,
    feed_url: 'https://example.com/feed',
    name: 'Test Feed',
    name_overridden: false,
    kind: 'rss',
    enabled: true,
    last_fetch_status: 'ok',
    last_fetch_at: '2026-06-29T10:00:00Z',
    last_error: null,
    item_count: 5,
    added_via: 'import',
  },
]

describe('FeedsTab', () => {
  const onUpdate = vi.fn()
  const onDelete = vi.fn()
  const onRefresh = vi.fn()

  it('shows empty state message when no feeds', () => {
    render(
      <FeedsTab feeds={[]} onUpdate={onUpdate} onDelete={onDelete} onRefresh={onRefresh} />,
    )
    expect(screen.getByText(/no feeds/i)).toBeInTheDocument()
  })

  it('renders feed list when feeds are present', () => {
    render(
      <FeedsTab feeds={feeds} onUpdate={onUpdate} onDelete={onDelete} onRefresh={onRefresh} />,
    )
    expect(screen.getByText('Test Feed')).toBeInTheDocument()
  })

  it('renders the import/export bar', () => {
    render(
      <FeedsTab feeds={[]} onUpdate={onUpdate} onDelete={onDelete} onRefresh={onRefresh} />,
    )
    expect(screen.getByRole('button', { name: /opml/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /markdown/i })).toBeInTheDocument()
  })
})
