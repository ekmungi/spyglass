// Tests for AddFeedBar's optional name field.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AddFeedBar } from './AddFeedBar'

// Preserve the real NotAFeedError so instanceof checks work.
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    addFeed: vi.fn(),
    discoverFeeds: vi.fn(),
  }
})

import * as api from '../lib/api'
import { NotAFeedError } from '../lib/api'

const onRefresh = vi.fn()

const FEED_STUB = {
  id: 1,
  feed_url: 'https://example.com/feed.xml',
  name: 'Example Feed',
  name_overridden: false,
  kind: 'rss',
  enabled: true,
  last_fetch_status: null,
  last_fetch_at: null,
  last_error: null,
  item_count: 0,
  added_via: 'manual',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AddFeedBar – name field', () => {
  it('renders a name input alongside the URL input', () => {
    render(<AddFeedBar onRefresh={onRefresh} />)
    expect(screen.getByPlaceholderText(/display name/i)).toBeInTheDocument()
  })

  it('passes the typed name to addFeed when name is non-empty', async () => {
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<AddFeedBar onRefresh={onRefresh} />)

    fireEvent.change(screen.getByPlaceholderText(/feed or page url/i), {
      target: { value: 'https://example.com/feed.xml' },
    })
    fireEvent.change(screen.getByPlaceholderText(/display name/i), {
      target: { value: 'My Feed' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      expect(api.addFeed).toHaveBeenCalledWith('https://example.com/feed.xml', 'My Feed')
    })
  })

  it('calls addFeed without name arg when name input is empty', async () => {
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<AddFeedBar onRefresh={onRefresh} />)

    fireEvent.change(screen.getByPlaceholderText(/feed or page url/i), {
      target: { value: 'https://example.com/feed.xml' },
    })
    // Leave name empty.
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      expect(api.addFeed).toHaveBeenCalledWith('https://example.com/feed.xml', undefined)
    })
  })

  it('still opens DiscoverPanel on NotAFeedError even when a name is provided', async () => {
    vi.mocked(api.addFeed).mockRejectedValue(new NotAFeedError('https://example.com'))
    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: [], reason: null })

    render(<AddFeedBar onRefresh={onRefresh} />)

    fireEvent.change(screen.getByPlaceholderText(/feed or page url/i), {
      target: { value: 'https://example.com' },
    })
    fireEvent.change(screen.getByPlaceholderText(/display name/i), {
      target: { value: 'Some Name' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      expect(api.discoverFeeds).toHaveBeenCalledWith('https://example.com', 'shallow')
    })
  })
})
