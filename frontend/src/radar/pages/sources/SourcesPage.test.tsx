// Tests for the Sources page: groups and wording, the feed switch, removal, adding a feed or a
// page, Collect now (including "already running"), and the error state.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import SourcesPage from '../SourcesPage'
import type { CollectorRow, FeedRow, SourcesView, StatusView } from './api'
import { timing } from './timing'
import { clearLoadCache } from './useLoad'

const api = vi.hoisted(() => ({
  loadSources: vi.fn(),
  loadStatus: vi.fn(),
  startCollect: vi.fn(),
  addFeed: vi.fn(),
  discoverFeeds: vi.fn(),
  setFeedEnabled: vi.fn(),
  removeFeed: vi.fn(),
  captureLink: vi.fn(),
}))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), ...api }))
// The FDA group reads the general settings; keep this file offline.
vi.mock('./fdaApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./fdaApi')>()),
  loadFdaSettings: vi.fn().mockResolvedValue({ enabled: true, productCodes: '', keywords: '' }),
}))

const recent = new Date(Date.now() - 3600_000).toISOString()

function feed(over: Partial<FeedRow> & { id: number; name: string }): FeedRow {
  return { url: `https://example.org/${over.id}/feed`, enabled: true, lastFetchAt: recent, status: 'ok', error: null, items: 4, ...over }
}

function collector(over: Partial<CollectorRow> & { key: string; label: string }): CollectorRow {
  return { status: 'ok', detail: null, lastRun: recent, newItems: 3, enabled: null, ...over }
}

function view(): SourcesView {
  return {
    feeds: [
      feed({ id: 1, name: 'Signal Ledger' }),
      feed({ id: 2, name: 'Policy Notes', status: 'error', error: 'HTTPError: 404 Client Error: Not Found for url' }),
    ],
    collectors: [
      collector({ key: 'news', label: 'News search', newItems: 11 }),
      collector({ key: 'hn', label: 'Hacker News', status: 'error', detail: 'ReadTimeout: HTTPSConnectionPool timed out' }),
      collector({ key: 'gmail', label: 'Email', status: 'ok' }),
      collector({ key: 'slack', label: 'Slack links', status: 'skipped', detail: 'not configured: no token' }),
      collector({ key: 'raindrop', label: 'Raindrop bookmarks', status: 'never', lastRun: null, newItems: null }),
    ],
  }
}

const idle: StatusView = { lastCollectAt: recent, nextBriefAt: new Date(Date.now() + 8 * 3600_000).toISOString(), running: false }

beforeEach(() => {
  clearLoadCache()
  vi.clearAllMocks()
  timing.pollMs = 20
  api.loadSources.mockResolvedValue(view())
  api.loadStatus.mockResolvedValue(idle)
  api.setFeedEnabled.mockResolvedValue({})
  api.removeFeed.mockResolvedValue({})
})

describe('SourcesPage', () => {
  it('shows the header line, the three groups and plain-language health', async () => {
    render(<SourcesPage />)
    expect(await screen.findByText(/Last collected/)).toHaveTextContent(/Next brief/)
    expect(screen.getByRole('heading', { name: 'From you' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Feeds' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Searches and signals' })).toBeInTheDocument()

    const fromYou = screen.getByRole('region', { name: 'From you' })
    expect(within(fromYou).getByText('Not configured')).toBeInTheDocument() // Slack
    expect(within(fromYou).getByText(/Slack needs a bot token/)).toBeInTheDocument()
    expect(within(fromYou).getByText(/set once in Spyglass.s settings file/)).toBeInTheDocument()
    expect(within(fromYou).getAllByRole('link', { name: 'setup guide' })[0]).toHaveAttribute('href', '#/settings')
    expect(fromYou).not.toHaveTextContent('.env')
    expect(within(fromYou).getByText('Configured')).toBeInTheDocument() // Gmail
    expect(within(fromYou).getByText('Waiting for its first run')).toBeInTheDocument() // Raindrop

    expect(screen.getByText('The address no longer exists; the site answered "not found".')).toBeInTheDocument()
    expect(screen.getByText('The site did not answer in time.')).toBeInTheDocument()
    expect(screen.queryByText(/HTTPError/)).not.toBeInTheDocument()
  })

  it('switches a feed off once the server has confirmed it', async () => {
    render(<SourcesPage />)
    const toggle = await screen.findByRole('switch', { name: 'Signal Ledger on or off' })
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(toggle)
    await waitFor(() => expect(api.setFeedEnabled).toHaveBeenCalledWith(1, false))
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Signal Ledger on or off' })).toHaveAttribute('aria-checked', 'false'))
  })

  it('leaves the switch alone and reports the problem when the change fails', async () => {
    api.setFeedEnabled.mockRejectedValue(new ApiError('feed not found', { status: 404, kind: 'http', path: '/api/feeds/1' }))
    render(<SourcesPage />)
    fireEvent.click(await screen.findByRole('switch', { name: 'Signal Ledger on or off' }))
    await waitFor(() => expect(api.setFeedEnabled).toHaveBeenCalled())
    expect(screen.getByRole('switch', { name: 'Signal Ledger on or off' })).toHaveAttribute('aria-checked', 'true')
  })

  it('removes a feed after confirmation', async () => {
    render(<SourcesPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Actions for Policy Notes' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove…' }))
    expect(api.removeFeed).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove feed' }))
    await waitFor(() => expect(api.removeFeed).toHaveBeenCalledWith(2))
    await waitFor(() => expect(screen.queryByText('Policy Notes')).not.toBeInTheDocument())
  })

  it('adds a feed from its address', async () => {
    api.addFeed.mockResolvedValue({ id: 9, name: 'New Blog', feed_url: 'https://new.example/feed', enabled: true })
    render(<SourcesPage />)
    fireEvent.change(await screen.findByLabelText('Add a feed'), { target: { value: 'https://new.example/feed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add feed' }))
    expect(await screen.findByText('Added New Blog.')).toBeInTheDocument()
    expect(api.addFeed).toHaveBeenCalledWith('https://new.example/feed')
    expect(screen.getByText('New Blog', { selector: '.rs-name' })).toBeInTheDocument()
  })

  it('finds the feeds on a web page and follows the one the reader picks', async () => {
    api.addFeed.mockRejectedValueOnce(new ApiError('That address is a web page, not a feed.', { status: 422, kind: 'http', path: '/api/feeds' }))
    api.discoverFeeds.mockResolvedValue({
      candidates: [{ feed_url: 'https://site.example/rss', name: 'Site RSS', kind: 'rss', already_subscribed: false }],
      reason: null,
    })
    api.addFeed.mockResolvedValueOnce({ id: 10, name: 'Site RSS', feed_url: 'https://site.example/rss', enabled: true })
    render(<SourcesPage />)
    fireEvent.change(await screen.findByLabelText('Add a feed'), { target: { value: 'https://site.example/' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add feed' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Follow Site RSS' }))
    expect(await screen.findByText('Added Site RSS.')).toBeInTheDocument()
    expect(api.addFeed).toHaveBeenLastCalledWith('https://site.example/rss')
  })

  it('explains in words when an address has no feed', async () => {
    api.addFeed.mockRejectedValue(new ApiError('Nothing at that address looks like a feed.', { status: 422, kind: 'http', path: '/api/feeds' }))
    api.discoverFeeds.mockResolvedValue({ candidates: [], reason: 'No feeds were found on that page.' })
    render(<SourcesPage />)
    fireEvent.change(await screen.findByLabelText('Add a feed'), { target: { value: 'https://nofeed.example/' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add feed' }))
    expect(await screen.findByText('No feeds were found on that page.')).toBeInTheDocument()
  })

  it('rejects an address that is not a web address before asking the server', async () => {
    render(<SourcesPage />)
    fireEvent.change(await screen.findByLabelText('Add a feed'), { target: { value: 'not a url' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add feed' }))
    expect(await screen.findByText(/Enter a full web address/)).toBeInTheDocument()
    expect(api.addFeed).not.toHaveBeenCalled()
  })

  it('collects now, waits for the run to end, then reloads the lists', async () => {
    api.startCollect.mockResolvedValue({ background: true, found: null })
    api.loadStatus.mockResolvedValueOnce(idle).mockResolvedValueOnce({ ...idle, running: true }).mockResolvedValue(idle)
    render(<SourcesPage />)
    await screen.findByText(/Last collected/)
    fireEvent.click(screen.getByRole('button', { name: 'Collect now' }))
    expect(await screen.findByRole('button', { name: 'Collecting…' })).toBeDisabled()
    expect(screen.getByText(/Collecting now/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Collect now' })).toBeEnabled()
    expect(api.loadSources.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('says automatic collection is switched off when the service answers 503, without a retry', async () => {
    api.startCollect.mockRejectedValue(new ApiError('Spyglass or a service it relies on is not responding. Try again shortly.', { status: 503, kind: 'http', path: '/collect', detail: 'the scheduler is not running' }))
    api.loadStatus.mockResolvedValue(idle)
    render(<SourcesPage />)
    await screen.findByText(/Last collected/)
    fireEvent.click(screen.getByRole('button', { name: 'Collect now' }))
    expect(await screen.findByText('Automatic collection is switched off in this copy of Spyglass.')).toBeInTheDocument()
    expect(screen.queryByText(/Try again/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collect now' })).toBeDisabled()
  })

  it('says a collection is already running when the server answers 409', async () => {
    api.startCollect.mockRejectedValue(new ApiError('This is already in progress. Try again in a moment.', { status: 409, kind: 'http', path: '/collect' }))
    api.loadStatus.mockResolvedValueOnce(idle).mockResolvedValue({ ...idle, running: true })
    render(<SourcesPage />)
    await screen.findByText(/Last collected/)
    fireEvent.click(screen.getByRole('button', { name: 'Collect now' }))
    expect(await screen.findByRole('button', { name: 'Collecting…' })).toBeDisabled()
    await act(async () => {})
    expect(screen.getByText(/Collecting now/)).toBeInTheDocument()
  })

  it('shows the failure and a retry when the sources cannot be loaded', async () => {
    api.loadSources.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/sources' }))
    render(<SourcesPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Feeds' })).toBeInTheDocument()
  })

  it('sends a link in from the Add a link box', async () => {
    api.captureLink.mockResolvedValue({ id: 1 })
    render(<SourcesPage />)
    fireEvent.change(await screen.findByLabelText('Add a link'), { target: { value: 'https://example.org/story' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }))
    await waitFor(() => expect(api.captureLink).toHaveBeenCalledWith({ url: 'https://example.org/story' }))
    expect(await screen.findByText(/Added\. It appears under From you/)).toBeInTheDocument()
  })
})
