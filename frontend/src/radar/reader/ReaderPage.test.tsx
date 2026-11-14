// Tests for the reader page's wait: the preparing message shows from the click until the copy is
// ready, gives way to the unavailable view when the copy fails, and offers Try again after a long wait.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ItemDetail, ReaderStatus } from '../api/types'
import { clearResourceCache } from '../hooks/useResource'
import { ReaderPage } from './ReaderPage'

const api = vi.hoisted(() => ({ getItem: vi.fn(), sendSignal: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const PREPARING = 'Preparing a clean copy and a summary of this article. The first time takes a few seconds.'
const SLOW = 'This is taking longer than usual.'

/** A minimal item whose reader copy has the given status. */
function detail(status: ReaderStatus): ItemDetail {
  return {
    id: 5,
    title: 'A title',
    headline: 'A headline',
    url: 'https://example.org/a',
    source: 'rss',
    origin: 'Example Wire',
    published_at: null,
    fetched_at: '2026-11-12T08:00:00',
    kind: 'news',
    section: '',
    section_label: '',
    tier: 'notable',
    score: null,
    why: null,
    key_points: [],
    entities: [],
    signal: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    has_reader: status === 'ok',
    summary: null,
    reader: { kind: 'article', html: '<p>The article body.</p>', title: null, byline: null, site: null, lead_image: null, word_count: 300, source_url: null, alt_url: null, status, error: null },
    related: [],
    story_sources: [],
    threads: [],
  } as unknown as ItemDetail
}

/** Let resolved requests and the timers due within `ms` run, inside React's act. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  clearResourceCache()
  vi.clearAllMocks()
  api.sendSignal.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('ReaderPage wait', () => {
  it('shows the preparing message once the item takes more than a moment to load', async () => {
    vi.useFakeTimers()
    api.getItem.mockReturnValue(new Promise(() => undefined))
    render(<ReaderPage id={5} />)
    expect(screen.queryByText(PREPARING)).not.toBeInTheDocument()
    await advance(400)
    expect(screen.getByRole('status')).toHaveTextContent(PREPARING)
  })

  it('never shows the preparing message for a ready item that arrives quickly', async () => {
    // A copy built earlier (most are built in the background) answers in well under a tenth of a second.
    vi.useFakeTimers()
    api.getItem.mockReturnValue(new Promise((resolve) => setTimeout(() => resolve(detail('ok')), 80)))
    render(<ReaderPage id={5} />)
    await advance(40)
    expect(screen.queryByText(PREPARING)).not.toBeInTheDocument()
    await advance(40)
    expect(screen.getByText('The article body.')).toBeInTheDocument()
    expect(screen.queryByText(PREPARING)).not.toBeInTheDocument()
  })

  it('says the wait is long when the item request runs past ten seconds, without Try again', async () => {
    // The server keeps building the copy while the request waits, so a second request would only wait on the same build.
    vi.useFakeTimers()
    api.getItem.mockReturnValue(new Promise(() => undefined))
    render(<ReaderPage id={5} />)
    await advance(9999)
    expect(screen.queryByText(SLOW)).not.toBeInTheDocument()
    await advance(1)
    expect(screen.getByText(SLOW)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('opens a ready item without the preparing message', async () => {
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    expect(await screen.findByText('The article body.')).toBeInTheDocument()
    expect(screen.queryByText(PREPARING)).not.toBeInTheDocument()
  })

  it('leaves the preparing view for the unavailable view when the copy fails after a wait', async () => {
    vi.useFakeTimers()
    api.getItem.mockResolvedValueOnce(detail('pending')).mockResolvedValueOnce(detail('failed'))
    render(<ReaderPage id={5} />)
    await advance(0)
    expect(screen.getByText(PREPARING)).toBeInTheDocument()
    await advance(3000)
    expect(api.getItem).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Spyglass could not make a clean copy of this page.')).toBeInTheDocument()
    expect(screen.queryByText(PREPARING)).not.toBeInTheDocument()
  })

  it('says the wait is long once polling stops, and Try again polls again', async () => {
    vi.useFakeTimers()
    api.getItem.mockResolvedValue(detail('pending'))
    render(<ReaderPage id={5} />)
    await advance(0)
    // An identical "pending" answer every time must not stop the polling early.
    for (let poll = 0; poll < 20; poll += 1) await advance(3000)
    expect(api.getItem).toHaveBeenCalledTimes(21)
    expect(screen.getByText(SLOW)).toBeInTheDocument()
    await advance(3000)
    expect(api.getItem).toHaveBeenCalledTimes(21)

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await advance(0)
    expect(api.getItem).toHaveBeenCalledTimes(22)
    expect(screen.queryByText(SLOW)).not.toBeInTheDocument()
    expect(screen.getByText(PREPARING)).toBeInTheDocument()
    await advance(3000)
    expect(api.getItem).toHaveBeenCalledTimes(23)
  })
})
