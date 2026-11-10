// Tests for DiscoverPanel: candidate rendering, already_subscribed badge,
// Search deeper, multi-select Add, empty state with reason.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FeedCandidate } from '../lib/types'
import { DiscoverPanel } from './DiscoverPanel'

vi.mock('../lib/api')

import * as api from '../lib/api'

const onRefresh = vi.fn()
const onClose = vi.fn()

const CANDIDATES: FeedCandidate[] = [
  { feed_url: 'https://example.com/feed.xml', name: 'Example Feed', kind: 'rss', already_subscribed: false },
  { feed_url: 'https://example.com/atom.xml', name: 'Example Atom', kind: 'rss', already_subscribed: true },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DiscoverPanel', () => {
  it('calls discoverFeeds with shallow depth on mount and renders candidates', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: CANDIDATES, reason: null })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      expect(api.discoverFeeds).toHaveBeenCalledWith('https://example.com', 'shallow')
      expect(screen.getByText('Example Feed')).toBeInTheDocument()
      expect(screen.getByText('Example Atom')).toBeInTheDocument()
    })
  })

  it('shows an already_subscribed badge for subscribed candidates', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: CANDIDATES, reason: null })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      expect(screen.getByText(/already subscribed/i)).toBeInTheDocument()
    })
  })

  it('calls discoverFeeds with depth="deep" when Search deeper is clicked', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: CANDIDATES, reason: null })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => screen.getByText('Example Feed'))

    vi.mocked(api.discoverFeeds).mockResolvedValue({ candidates: [], reason: null })
    fireEvent.click(screen.getByRole('button', { name: /search deeper/i }))

    await waitFor(() => {
      expect(api.discoverFeeds).toHaveBeenCalledWith('https://example.com', 'deep')
    })
  })

  it('calls addFeed for each selected candidate then refreshes and closes', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [CANDIDATES[0]],
      reason: null,
    })
    vi.mocked(api.addFeed).mockResolvedValue({
      id: 2,
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
    })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    // Wait for candidates to load, then check the checkbox, then click Add selected.
    await waitFor(() => screen.getByText('Example Feed'))

    const checkbox = screen.getByRole('checkbox', { name: /example feed/i })
    expect((checkbox as HTMLInputElement).checked).toBe(true) // unsubscribed starts checked

    fireEvent.click(screen.getByRole('button', { name: /add selected/i }))

    await waitFor(() => {
      expect(api.addFeed).toHaveBeenCalledWith('https://example.com/feed.xml')
      expect(api.addFeed).toHaveBeenCalledTimes(1)
      expect(onRefresh).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('renders the reason text when candidates is empty', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'site blocked discovery',
    })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      // Assert the reason-bearing format (not the fallback "No feeds found on this page").
      expect(screen.getByText(/no feeds found: site blocked discovery/i)).toBeInTheDocument()
    })
  })

  it('does not add already_subscribed candidates by default', async () => {
    // Only subscribed candidate available.
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [CANDIDATES[1]],
      reason: null,
    })
    vi.mocked(api.addFeed).mockResolvedValue({
      id: 3,
      feed_url: 'https://example.com/atom.xml',
      name: 'Example Atom',
      name_overridden: false,
      kind: 'rss',
      enabled: true,
      last_fetch_status: null,
      last_fetch_at: null,
      last_error: null,
      item_count: 0,
      added_via: 'manual',
    })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)
    await waitFor(() => screen.getByText('Example Atom'))

    // Already-subscribed checkbox should be unchecked by default.
    const checkbox = screen.getByRole('checkbox', { name: /example atom/i })
    expect((checkbox as HTMLInputElement).checked).toBe(false)
  })
})
