// Tests for the reader page's wait (the preparing message shows from the click until the copy is
// ready, gives way to the unavailable view when the copy fails, and offers Try again after a long
// wait), the line under the title, the next-story block at the end, and the J and K keys.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ItemDetail, ReaderStatus, TodayResponse } from '../api/types'
import { clearResourceCache, useResource } from '../hooks/useResource'
import { resetReadingList, setReadingList } from '../state/readingList'
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
  resetReadingList()
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

/** A ready item with a site, a date and a 10-minute reading time, and the given byline. */
function described(byline: string | null): ItemDetail {
  const ready = detail('ok')
  return {
    ...ready,
    published_at: '2026-11-12T08:00:00Z',
    reader: { ...(ready.reader as NonNullable<ItemDetail['reader']>), site: 'Example Site', byline, word_count: 2300 },
  }
}

describe('the line under the title', () => {
  it('joins the byline with the source, the date and the reading time, none of which stay in the bar', async () => {
    api.getItem.mockResolvedValue(described('Ada Lovelace'))
    const { container } = render(<ReaderPage id={5} />)
    expect(await screen.findByText('Ada Lovelace · Example Site · 12 Nov 2026 · 10 min read')).toHaveClass('r-reader__byline')
    expect(container.querySelector('.r-readerbar')?.textContent).not.toMatch(/Example Site|12 Nov 2026|min read/)
  })

  it('shows the source, the date and the reading time alone when there is no byline', async () => {
    api.getItem.mockResolvedValue(described(null))
    render(<ReaderPage id={5} />)
    expect(await screen.findByText('Example Site · 12 Nov 2026 · 10 min read')).toHaveClass('r-reader__byline')
  })

  it('says "PDF · N pages" for a long PDF, never "min read"', async () => {
    const ready = detail('ok')
    api.getItem.mockResolvedValue({ ...ready, reader: { ...(ready.reader as NonNullable<ItemDetail['reader']>), kind: 'pdf', word_count: 90000, page_count: 212 } })
    render(<ReaderPage id={5} />)
    expect(await screen.findByText(/PDF · 212 pages/)).toHaveClass('r-reader__byline')
    expect(screen.queryByText(/min read/)).not.toBeInTheDocument()
  })
})

// Twenty-seven stories; the reader has the second one (id 5) open and the third is id 6.
const LIST = [4, 5, 6, ...Array.from({ length: 24 }, (_, index) => 200 + index)]
const NEXT_HEADLINE = 'Northfield Robotics clears its second surgical platform in Europe'

/** Today's answer as the Today page leaves it in the cache: one section whose story leads with item 6. */
const TODAY = {
  brief: { day: '2026-11-25', sections: [{ key: 'top', title: 'Top stories', note: null, stories: [{ id: 's6', item_id: 6, headline: NEXT_HEADLINE }] }] },
  days: [],
  status: {},
} as unknown as TodayResponse

/** Load Today's answer into the cache the way the Today page does, then leave. */
async function visitToday() {
  function TodayVisit() {
    const today = useResource('today', async () => TODAY)
    return today.data ? <p>Today loaded</p> : null
  }
  render(<TodayVisit />)
  await screen.findByText('Today loaded')
  cleanup()
}

describe('the next story at the end', () => {
  it('offers "Next in Today · 3 of 27" with the headline Today holds, and opens it in place of this one', async () => {
    await visitToday()
    window.history.replaceState(null, '', '/#/item/5')
    setReadingList('Today', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    const next = await screen.findByRole('link', { name: /^Next in Today · 3 of 27/ })
    expect(next).toHaveTextContent(NEXT_HEADLINE)
    const entries = window.history.length
    fireEvent.click(next)
    expect(window.location.hash).toBe('#/item/6')
    expect(window.history.length).toBe(entries)
  })

  it('takes the headline of a story opened earlier in the reader', async () => {
    api.getItem.mockResolvedValue({ ...detail('ok'), id: 6, headline: NEXT_HEADLINE })
    render(<ReaderPage id={6} />)
    await screen.findByText('The article body.')
    cleanup()
    setReadingList('the Feed', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    expect(await screen.findByRole('link', { name: /^Next in the Feed · 3 of 27/ })).toHaveTextContent(NEXT_HEADLINE)
  })

  it("takes the headline from an earlier day's brief when the reader was opened from that day", async () => {
    function DayVisit() {
      const brief = useResource('brief:2026-11-20', async () => TODAY.brief)
      return brief.data ? <p>Day loaded</p> : null
    }
    render(<DayVisit />)
    await screen.findByText('Day loaded')
    cleanup()
    window.history.replaceState({ radarIndex: 1, radarFrom: '#/today/2026-11-20' }, '', '/#/item/5')
    setReadingList('Today', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    expect(await screen.findByRole('link', { name: /^Next in Today · 3 of 27/ })).toHaveTextContent(NEXT_HEADLINE)
  })

  it('shows the position alone as the link when nothing holds the next headline', async () => {
    setReadingList('the Feed', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    const next = await screen.findByRole('link', { name: 'Next in the Feed · 3 of 27' })
    expect(next).toHaveTextContent(/^Next in the Feed · 3 of 27$/)
  })

  it('shows nothing after the last story of the list, or without a list', async () => {
    setReadingList('Today', [4, 5])
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    await screen.findByText('The article body.')
    expect(screen.queryByText(/^Next in /)).not.toBeInTheDocument()
    cleanup()
    resetReadingList()
    render(<ReaderPage id={5} />)
    await screen.findByText('The article body.')
    expect(screen.queryByText(/^Next in /)).not.toBeInTheDocument()
  })
})

describe('the J and K keys', () => {
  it('J opens the next story and K the previous one, each in place of this one', async () => {
    window.history.replaceState(null, '', '/#/item/5')
    setReadingList('Today', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    await screen.findByText('The article body.')
    const entries = window.history.length
    fireEvent.keyDown(window, { key: 'j' })
    expect(window.location.hash).toBe('#/item/6')
    fireEvent.keyDown(window, { key: 'k' })
    expect(window.location.hash).toBe('#/item/4')
    expect(window.history.length).toBe(entries)
  })

  it('does nothing while the focus is in a text field or a text area, or without a list', async () => {
    window.history.replaceState(null, '', '/#/item/5')
    setReadingList('Today', LIST)
    api.getItem.mockResolvedValue(detail('ok'))
    render(<ReaderPage id={5} />)
    await screen.findByText('The article body.')
    const field = document.body.appendChild(document.createElement('input'))
    const area = document.body.appendChild(document.createElement('textarea'))
    fireEvent.keyDown(field, { key: 'j' })
    fireEvent.keyDown(area, { key: 'k' })
    expect(window.location.hash).toBe('#/item/5')
    field.remove()
    area.remove()
    act(() => resetReadingList())
    fireEvent.keyDown(window, { key: 'j' })
    expect(window.location.hash).toBe('#/item/5')
  })
})
