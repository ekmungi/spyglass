// Click-through test of the whole shell against the sample-mode fetch: Today -> reader -> Back,
// the assistant streaming an answer, and the Feed's Saved filter.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from './api/transport'
import RadarApp from './App'
import { setAssistOpen, setAssistTarget } from './assistant/assistStore'
import { resetConversations } from './assistant/useThread'
import { clearResourceCache } from './hooks/useResource'
import { mockFetch, resetMockState } from './mock'
import { navigate } from './router'
import { resetItemState } from './state/itemState'

beforeEach(() => {
  resetMockState()
  resetConversations()
  clearResourceCache()
  resetItemState()
  window.localStorage.clear()
  setAssistTarget(null)
  setAssistOpen('reader', true)
  setAssistOpen('today', false)
  window.history.replaceState(null, '', '/#/today')
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('RadarApp', () => {
  it('opens a story over Today and returns to it with Back', async () => {
    render(<RadarApp />)
    const headline = await screen.findByText(/Aster AI releases Aster 4/, {}, { timeout: 4000 })
    fireEvent.click(headline.closest('a') as HTMLAnchorElement)

    const title = await screen.findByRole('heading', { level: 1, name: /Aster AI releases Aster 4/ }, { timeout: 4000 })
    const reader = title.closest('.r-layer--reader') as HTMLElement
    expect(within(reader).getByText('Why it matters to you')).toBeInTheDocument()
    expect(within(reader).getByText(/fall by about 60 percent from next month/)).toBeInTheDocument()
    // The article's table is wrapped for sideways scrolling.
    await waitFor(() => expect(reader.querySelector('.r-table-wrap table')).not.toBeNull())
    // The page underneath stays mounted but hidden and inert.
    const pageLayer = document.querySelector('.r-layer--page') as HTMLElement
    expect(pageLayer.dataset.hidden).toBe('true')
    expect(pageLayer.hasAttribute('inert')).toBe(true)

    fireEvent.click(within(reader).getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(document.querySelector('.r-layer--reader')).toBeNull())
    expect(window.location.hash).toBe('#/today')
    expect(pageLayer.dataset.hidden).toBeUndefined()
    // The opened story is now marked as read.
    expect(screen.getByText(/Aster AI releases Aster 4/).closest('li')?.className).toContain('is-read')
  })

  it('keeps the rail on the page the reader was opened from', async () => {
    render(<RadarApp />)
    await screen.findByText('Top stories', {}, { timeout: 4000 })
    act(() => navigate({ name: 'feed', params: {} }))
    await screen.findByText(/^35 items$/, {}, { timeout: 4000 })
    const rail = within(screen.getByRole('navigation', { name: 'Main' }))
    expect(rail.getByRole('link', { name: 'Feed' })).toHaveAttribute('aria-current', 'page')

    act(() => navigate({ name: 'item', id: 101 }))
    await screen.findByRole('heading', { level: 1, name: /Aster AI releases Aster 4/ }, { timeout: 4000 })
    expect(rail.getByRole('link', { name: 'Feed' })).toHaveAttribute('aria-current', 'page')
    expect(rail.getByRole('link', { name: 'Today' })).not.toHaveAttribute('aria-current')
  })

  it('remembers where the reader was opened from across a reload', async () => {
    // What the router stores in the history entry when a reader is opened from the Feed.
    window.history.replaceState({ radarIndex: 1, radarFrom: '#/feed?section=health' }, '', '/#/item/101')
    render(<RadarApp />)
    await screen.findByRole('heading', { level: 1, name: /Aster AI releases Aster 4/ }, { timeout: 4000 })
    const rail = within(screen.getByRole('navigation', { name: 'Main' }))
    expect(rail.getByRole('link', { name: 'Feed' })).toHaveAttribute('aria-current', 'page')
  })

  it('falls back to Today for a reader opened cold', async () => {
    window.history.replaceState(null, '', '/#/item/101')
    render(<RadarApp />)
    await screen.findByRole('heading', { level: 1, name: /Aster AI releases Aster 4/ }, { timeout: 4000 })
    const rail = within(screen.getByRole('navigation', { name: 'Main' }))
    expect(rail.getByRole('link', { name: 'Today' })).toHaveAttribute('aria-current', 'page')
  })

  it('streams an assistant answer for a quick action in the reader', async () => {
    window.history.replaceState(null, '', '/#/item/101')
    render(<RadarApp />)
    const panel = await screen.findByRole('complementary', { name: 'Assistant' }, { timeout: 4000 })
    const explain = await within(panel).findByRole('button', { name: 'Explain' }, { timeout: 4000 })
    fireEvent.click(explain)
    expect(await within(panel).findByText(/can now read a whole long document at once/, {}, { timeout: 8000 })).toBeInTheDocument()
    await within(panel).findByRole('button', { name: 'Copy' }, { timeout: 8000 })
    // The user's turn shows the action label even though its content was empty.
    expect(within(panel).getAllByText('Explain').length).toBeGreaterThan(0)
  }, 15000)

  it('filters the Feed to saved items', async () => {
    render(<RadarApp />)
    await screen.findByText('Top stories', {}, { timeout: 4000 })
    act(() => navigate({ name: 'feed', params: {} }))
    await screen.findByRole('heading', { level: 1, name: 'Feed' })
    await screen.findByText(/^35 items$/, {}, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: 'Saved' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed?saved=true'))
    // The day heading above the rows also reads "2 items" when all saved items fall on one day, so the page total is matched by its own class.
    await screen.findByText('2 items', { selector: '.r-page-meta' }, { timeout: 4000 })
    expect(screen.getByText(/Corvid Systems ships an open-weight vision model/)).toBeInTheDocument()
  })
})

describe('arriving at a page', () => {
  it('starts a page opened from the rail at the top, and restores the place only on Back', async () => {
    window.history.replaceState(null, '', '/#/sources')
    render(<RadarApp />)
    const rail = within(screen.getByRole('navigation', { name: 'Main' }))
    const layer = document.querySelector('.r-layer--page') as HTMLElement
    layer.scrollTop = 780
    fireEvent.scroll(layer)

    fireEvent.click(rail.getByRole('link', { name: 'Watch' }))
    await waitFor(() => expect(window.location.hash).toBe('#/watch'))
    expect(layer.scrollTop).toBe(0)

    // Forward again to Sources by a click: always the top, even though 780 was remembered.
    fireEvent.click(rail.getByRole('link', { name: 'Sources' }))
    await waitFor(() => expect(window.location.hash).toBe('#/sources'))
    expect(layer.scrollTop).toBe(0)

    // Browser Back to Watch restores Watch's own place.
    layer.scrollTop = 0
    fireEvent.click(rail.getByRole('link', { name: 'Watch' }))
    layer.scrollTop = 300
    fireEvent.scroll(layer)
    fireEvent.click(rail.getByRole('link', { name: 'Feed' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed'))
    const popped = new Promise((resolve) => window.addEventListener('popstate', resolve, { once: true }))
    window.history.back()
    await popped
    await waitFor(() => expect(window.location.hash).toBe('#/watch'))
    expect(layer.scrollTop).toBe(300)
  })

  it('shows "That page does not exist" with a link to Today for an unknown address', async () => {
    window.history.replaceState(null, '', '/#/nowhere')
    render(<RadarApp />)
    expect(await screen.findByRole('heading', { name: 'That page does not exist' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Go to Today' }))
    await waitFor(() => expect(window.location.hash).toBe('#/today'))
  })
})
