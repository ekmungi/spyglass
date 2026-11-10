// Tests for FeedList: table of feeds delegating to FeedRow.
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FeedData } from '../lib/types'
import { FeedList } from './FeedList'

vi.mock('../lib/api')

const feeds: FeedData[] = [
  {
    id: 1,
    feed_url: 'https://a.com/feed',
    name: 'Feed A',
    name_overridden: false,
    kind: 'rss',
    enabled: true,
    last_fetch_status: 'ok',
    last_fetch_at: '2026-06-29T10:00:00Z',
    last_error: null,
    item_count: 10,
    added_via: 'import',
  },
  {
    id: 2,
    feed_url: 'https://b.com/feed',
    name: 'Feed B',
    name_overridden: false,
    kind: 'atom',
    enabled: false,
    last_fetch_status: 'error',
    last_fetch_at: null,
    last_error: 'timeout',
    item_count: 0,
    added_via: 'import',
  },
]

describe('FeedList', () => {
  const onUpdate = vi.fn()
  const onDelete = vi.fn()

  it('renders a row for each feed', () => {
    render(<FeedList feeds={feeds} onUpdate={onUpdate} onDelete={onDelete} />)
    expect(screen.getByText('Feed A')).toBeInTheDocument()
    expect(screen.getByText('Feed B')).toBeInTheDocument()
  })

  it('renders table headers', () => {
    render(<FeedList feeds={feeds} onUpdate={onUpdate} onDelete={onDelete} />)
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('URL')).toBeInTheDocument()
    expect(screen.getByText('Items')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
  })
})
