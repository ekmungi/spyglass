// Tests for AddFeedBar: URL input + Add flow, not_a_feed branch, generic error branch.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AddFeedBar } from './AddFeedBar'

// Mock the api module but preserve the real NotAFeedError class so that
// `err instanceof NotAFeedError` works correctly inside AddFeedBar.
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

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AddFeedBar', () => {
  it('renders a URL input and an Add button', () => {
    render(<AddFeedBar onRefresh={onRefresh} />)
    expect(screen.getByPlaceholderText(/url/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
  })

  it('calls addFeed with the typed URL on success, clears input, and refreshes', async () => {
    vi.mocked(api.addFeed).mockResolvedValue({
      id: 1,
      feed_url: 'https://example.com/feed.xml',
      name: 'Example',
      name_overridden: false,
      kind: 'rss',
      enabled: true,
      last_fetch_status: null,
      last_fetch_at: null,
      last_error: null,
      item_count: 0,
      added_via: 'manual',
    })

    render(<AddFeedBar onRefresh={onRefresh} />)
    const input = screen.getByPlaceholderText(/url/i)

    fireEvent.change(input, { target: { value: 'https://example.com/feed.xml' } })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      // Name input left empty -> addFeed called with url and undefined name.
      expect(api.addFeed).toHaveBeenCalledWith('https://example.com/feed.xml', undefined)
      expect(onRefresh).toHaveBeenCalled()
    })
    // Input should be cleared after success.
    expect((input as HTMLInputElement).value).toBe('')
  })

  it('opens DiscoverPanel when addFeed rejects with NotAFeedError', async () => {
    vi.mocked(api.addFeed).mockRejectedValue(new NotAFeedError('https://example.com'))
    // discoverFeeds must be mocked so DiscoverPanel can load without error.
    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: [], reason: 'No feeds found' })

    render(<AddFeedBar onRefresh={onRefresh} />)
    fireEvent.change(screen.getByPlaceholderText(/url/i), {
      target: { value: 'https://example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    // DiscoverPanel should appear (it calls discoverFeeds on mount).
    await waitFor(() => {
      expect(api.discoverFeeds).toHaveBeenCalledWith('https://example.com', 'shallow')
    })
  })

  it('shows an error message and does NOT open DiscoverPanel on a generic failure', async () => {
    vi.mocked(api.addFeed).mockRejectedValue(new Error('POST /api/feeds failed: 500'))

    render(<AddFeedBar onRefresh={onRefresh} />)
    fireEvent.change(screen.getByPlaceholderText(/url/i), {
      target: { value: 'https://example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    // discoverFeeds should not have been called — no panel opened.
    expect(api.discoverFeeds).not.toHaveBeenCalled()
  })
})
