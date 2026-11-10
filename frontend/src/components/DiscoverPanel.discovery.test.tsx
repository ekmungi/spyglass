// Tests for DiscoverPanel's reason_code display and Google News affordance.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DiscoverPanel } from './DiscoverPanel'

vi.mock('../lib/api')

import * as api from '../lib/api'

const onRefresh = vi.fn()
const onClose = vi.fn()

const FEED_STUB = {
  id: 1,
  feed_url: 'https://news.google.com/rss/search?q=site%3Aexample.com&hl=en-US&gl=US&ceid=US%3Aen',
  name: 'Google News – example.com',
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

describe('DiscoverPanel – blocked reason_code', () => {
  it('shows the backend reason text when reason_code is blocked', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Cloudflare bot protection detected',
      reason_code: 'blocked',
    })

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      expect(
        screen.getByText(/cloudflare bot protection detected/i),
      ).toBeInTheDocument()
    })
  })

  it('shows the Subscribe via Google News section when reason_code is blocked', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Bot protection detected',
      reason_code: 'blocked',
    })

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      // The section heading paragraph and the submit button both contain this text;
      // assert the button specifically to confirm the full affordance is rendered.
      expect(
        screen.getByRole('button', { name: /subscribe via google news/i }),
      ).toBeInTheDocument()
    })
  })

  it('prefills the site field with the hostname stripped of www.', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Blocked',
      reason_code: 'blocked',
    })

    render(<DiscoverPanel url="https://www.example.com/topics/ai" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      const siteInput = screen.getByPlaceholderText(/site/i) as HTMLInputElement
      expect(siteInput.value).toBe('example.com')
    })
  })

  it('calls addFeed with the Google News URL built from site field on submit, then refreshes and closes', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Blocked',
      reason_code: 'blocked',
    })
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() =>
      screen.getByRole('button', { name: /subscribe via google news/i }),
    )

    fireEvent.click(screen.getByRole('button', { name: /subscribe via google news/i }))

    await waitFor(() => {
      // The URL must contain site:example.com in its q param.
      const calledUrl = (api.addFeed as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
      const q = decodeURIComponent(new URL(calledUrl).searchParams.get('q') ?? '')
      expect(q).toContain('site:example.com')
      expect(onRefresh).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('passes an optional topic when topic input is filled', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Blocked',
      reason_code: 'blocked',
    })
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() =>
      screen.getByRole('button', { name: /subscribe via google news/i }),
    )

    fireEvent.change(screen.getByPlaceholderText(/topic/i), { target: { value: 'AI health' } })
    fireEvent.click(screen.getByRole('button', { name: /subscribe via google news/i }))

    await waitFor(() => {
      const calledUrl = (api.addFeed as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
      const q = decodeURIComponent(new URL(calledUrl).searchParams.get('q') ?? '')
      expect(q).toContain('AI health')
      expect(q).toContain('site:example.com')
    })
  })

  it('passes the name arg to addFeed when name input is filled', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Blocked',
      reason_code: 'blocked',
    })
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() =>
      screen.getByRole('button', { name: /subscribe via google news/i }),
    )

    fireEvent.change(screen.getByPlaceholderText(/display name/i), {
      target: { value: 'My Health News' },
    })
    fireEvent.click(screen.getByRole('button', { name: /subscribe via google news/i }))

    await waitFor(() => {
      expect(api.addFeed).toHaveBeenCalledWith(
        expect.stringContaining('news.google.com'),
        'My Health News',
      )
    })
  })

  it('calls addFeed without name arg when name input is left empty', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'Blocked',
      reason_code: 'blocked',
    })
    vi.mocked(api.addFeed).mockResolvedValue(FEED_STUB)

    render(<DiscoverPanel url="https://www.example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() =>
      screen.getByRole('button', { name: /subscribe via google news/i }),
    )
    fireEvent.click(screen.getByRole('button', { name: /subscribe via google news/i }))

    await waitFor(() => {
      // Called with only one arg (the URL), no name.
      expect(api.addFeed).toHaveBeenCalledWith(
        expect.stringContaining('news.google.com'),
        undefined,
      )
    })
  })
})

describe('DiscoverPanel – no_feeds reason_code', () => {
  it('shows the no-feeds reason text and does NOT show Google News affordance', async () => {
    vi.mocked(api.discoverFeeds).mockResolvedValue({
      candidates: [],
      reason: 'No feeds found on this page',
      reason_code: 'no_feeds',
    })

    render(<DiscoverPanel url="https://example.com" onRefresh={onRefresh} onClose={onClose} />)

    await waitFor(() => {
      expect(screen.getByText(/no feeds found on this page/i)).toBeInTheDocument()
      expect(screen.queryByText(/subscribe via google news/i)).not.toBeInTheDocument()
    })
  })
})
