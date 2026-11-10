// Tests for the application shell: data loading, segmented tabs, workspace wiring.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './lib/api'
import { makeBrief, makeCard } from './test/fixtures'
import type { CardData } from './lib/types'

// virtua needs real layout (absent in jsdom); render its children directly so the list
// rows are present for these behavioral assertions. Real virtualization is verified in-browser.
vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const cards: CardData[] = [
  makeCard({ id: 1, title: 'First card', summary: 'Summary one', relevance: 'high' }),
  makeCard({
    id: 2,
    title: 'Second card',
    summary: 'Summary two',
    source: 'raindrop',
    created_at: '2026-06-10T07:00:00Z',
  }),
]

function stubFetch(cardData: CardData[] = cards) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
    if (url.includes('/api/refresh')) return respond({ refreshed: true, sources: 2 })
    if (url.includes('/fulltext')) return respond({ status: 'ok', markdown: 'Stored text.' })
    // Daily Brief endpoints; the fixture's markdown links card:1 -> 'First card'.
    if (url.includes('/api/briefs/7')) return respond(makeBrief({ id: 7 }))
    if (url.includes('/api/briefs')) return respond([makeBrief({ id: 7 })])
    if (url.includes('/api/search')) {
      return respond([{ ...cardData[1], snippet: 'matched [text]' }].filter(Boolean))
    }
    if (url.includes('/api/categories')) return respond([])
    if (url.includes('/api/cards/1')) return respond({ ...cardData[0], state: 'new' })
    if (url.includes('/api/cards')) return respond(cardData)
    if (url.includes('/api/runs')) return respond([])
    if (url.includes('/api/selection')) return respond({ card_ids: [1] })
    return respond({})
  })
}

describe('App', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
    vi.stubGlobal('fetch', stubFetch())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('refreshes if stale on open and renders the workspace rows', async () => {
    render(<App />)
    expect(await screen.findByText('First card')).toBeInTheDocument()
    const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
    expect(calls.some((u) => u.includes('/api/refresh?if_stale=true'))).toBe(true)
  })

  it('centers the layout at the user-adjustable max width (mockup .wrap)', async () => {
    const { container } = render(<App />)
    await screen.findByText('First card')
    const wrap = container.querySelector('main > div') as HTMLElement
    expect(wrap.style.maxWidth).toBe('var(--layout-max-width)')
    expect(wrap.className).toContain('mx-auto')
  })

  it('shows the tabs as a segmented control, Brief first (the MVP front door)', async () => {
    render(<App />)
    await screen.findByText('First card')
    for (const tab of ['Brief', 'Workspace', 'Activity', 'Settings']) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument()
    }
    // Brief leads the tab order deliberately.
    const group = screen.getByRole('group', { name: 'Tabs' })
    expect(group.querySelector('button')).toHaveTextContent('Brief')
    // "Archive" is also used as the label for per-row action buttons; find the
    // tab button specifically via the aria-pressed attribute set by SegmentedControl.
    expect(
      screen.getAllByRole('button', { name: 'Archive' })
        .find((btn) => btn.hasAttribute('aria-pressed')),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('opens a row in the reader pane', async () => {
    render(<App />)
    fireEvent.click(await screen.findByText('First card'))
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
  })

  it('reveals the filter panel when Filter is toggled', async () => {
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    expect(screen.getByLabelText('Source')).toBeInTheDocument()
  })

  it('switches to the Activity tab', async () => {
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('button', { name: 'Activity' }))
    expect(await screen.findByText(/no runs/i)).toBeInTheDocument()
  })

  it('surfaces a failed refresh in the status line instead of a white screen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('down', { status: 503 })),
    )
    render(<App />)
    expect(await screen.findByText(/failed: 503/)).toBeInTheDocument()
  })

  it('forces a full refresh when the Refresh button is clicked', async () => {
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
      // A forced refresh omits if_stale (distinct from the on-open if_stale=true).
      expect(calls.some((u) => u.endsWith('/api/refresh'))).toBe(true)
    })
  })

  it('searches the full text through the service', async () => {
    render(<App />)
    await screen.findByText('First card')
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'second' },
    })
    expect(await screen.findByText('Second card')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('First card')).not.toBeInTheDocument())
  })

  it('lists archived cards under the Archive tab and can unarchive them', async () => {
    vi.stubGlobal('fetch', stubFetch([makeCard({ id: 1, title: 'First card', state: 'dismissed' })]))
    render(<App />)
    await screen.findByRole('button', { name: 'Archive' })
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(await screen.findByText('First card')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /unarchive/i }))
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
      expect(calls.some((u) => u.includes('/api/cards/1'))).toBe(true)
    })
  })

  it('routes a card: link inside a brief to the workspace reader', async () => {
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('button', { name: 'Brief' }))
    // Open the (only) brief from the list, then follow its card:1 link.
    fireEvent.click(await screen.findByText('Daily Brief — Jul 1, 2026'))
    fireEvent.click(await screen.findByRole('link', { name: 'First card' }))
    // The app switches to the Workspace tab and the reader opens card 1.
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('leaves ordinary external links in a brief unrouted', async () => {
    vi.stubGlobal('fetch', stubFetch())
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('button', { name: 'Brief' }))
    fireEvent.click(await screen.findByText('Daily Brief — Jul 1, 2026'))
    await screen.findByRole('link', { name: 'First card' })
    // The https link renders as a normal anchor with its href intact.
    const external = screen.getByRole('link', { name: 'the web' })
    expect(external).toHaveAttribute('href', 'https://example.com')
    // Still on the Brief tab; nothing routed.
    expect(screen.getByRole('button', { name: 'Brief' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('sends the ticked cards with Open Claude Code', async () => {
    // No session linked here, so the cards travel with the request that opens a linked one.
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    fireEvent.click(screen.getByRole('button', { name: /open claude code/i }))
    await waitFor(() => {
      const open = (fetch as ReturnType<typeof vi.fn>).mock.calls.find((c) =>
        String(c[0]).includes('/api/link/open'),
      )
      expect(JSON.parse(String(open?.[1]?.body)).card_ids).toEqual([1])
    })
  })
})
