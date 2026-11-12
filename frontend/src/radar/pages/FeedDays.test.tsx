// The Feed's date headings: "Today", "Yesterday", then the weekday and date, each with how many
// items fall on that day. They are rows of the list, are skipped by j / k, and appear only where
// the list is in time order (not in the "Related" and "From the assistant's answer" lists, nor in Missed).
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { mockState, patchItem } from '../mock/store'
import { useRoute } from '../router'
import { FeedPage } from './FeedPage'

/** Thursday 12 November 2026, mid-afternoon in the machine's own zone. */
const NOW = new Date(2026, 10, 12, 15, 0)

/** The Feed as the app mounts it: its parameters come from the address. */
function RoutedFeed({ active = true }: { active?: boolean }) {
  const route = useRoute()
  return <FeedPage params={route.name === 'feed' ? route.params : {}} active={active} />
}

beforeEach(() => {
  // Only the clock is faked: the sample service's delays and the page's timers stay real.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
  resetMockState()
  clearResourceCache()
  clearFeedCache()
  window.history.replaceState(null, '', '/#/feed')
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  vi.useRealTimers()
})

/** Every row of the list in order: a heading as its title, an item as its headline. */
function rows(): string[] {
  return [...document.querySelectorAll('.r-feed > li')].map((node) =>
    node.classList.contains('r-feed-day') ? `# ${node.querySelector('h2')?.textContent}` : (node.querySelector('.r-feedrow__headline')?.textContent ?? ''),
  )
}

const headings = () => [...document.querySelectorAll('.r-feed-day')]
const startOfToday = new Date(2026, 10, 12).getTime()
const shown = () => mockState().items.filter((item) => item.tier !== 'out')

describe('date headings', () => {
  it('put Today and Yesterday over their days, with the number of items each holds', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const today = shown().filter((item) => Date.parse(item.published_at ?? '') >= startOfToday).length
    const yesterday = shown().length - today
    expect(headings().map((node) => node.textContent)).toEqual([`Today${today} items`, `Yesterday${yesterday} items`])
    expect(rows()[0]).toBe('# Today')
    expect(rows().indexOf('# Yesterday')).toBe(today + 1)
  })

  it('name an older day by its weekday and date, and say "1 item" for a single one', async () => {
    patchItem(140, { published_at: new Date(2026, 10, 9, 10, 0).toISOString() }) // Monday
    render(<RoutedFeed />)
    await waitFor(() => expect(rows()).toContain('# Monday 9 November'))
    const heading = headings().find((node) => node.textContent?.startsWith('Monday'))
    expect(heading?.textContent).toBe('Monday 9 November1 item')
  })

  it('split at local midnight', async () => {
    patchItem(101, { published_at: new Date(2026, 10, 11, 23, 59).toISOString() }) // was 5 h ago, now just before midnight
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const list = rows()
    expect(list.indexOf('Aster AI releases Aster 4 with a million-token context and lower prices')).toBeGreaterThan(list.indexOf('# Yesterday'))
  })

  it('are headings of the list, not items: no link, button or tab stop in them', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    for (const heading of headings()) {
      expect(heading.querySelector('a, button, input, [tabindex]')).toBeNull()
      expect(heading.querySelector('h2')).not.toBeNull()
    }
  })

  it('are skipped by j and k, which move between items only', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const today = shown().filter((item) => Date.parse(item.published_at ?? '') >= startOfToday).length
    const selected = () => document.querySelector('.r-feedrow.is-selected')
    for (let press = 0; press < today; press += 1) fireEvent.keyDown(window, { key: 'j' })
    // The last item of Today is selected; one more press lands on the first item of Yesterday.
    expect(selected()?.getAttribute('data-row-index')).toBe(String(today - 1))
    fireEvent.keyDown(window, { key: 'j' })
    expect(selected()?.getAttribute('data-row-index')).toBe(String(today))
    expect(selected()?.previousElementSibling?.classList.contains('r-feed-day')).toBe(true)
    fireEvent.keyDown(window, { key: 'k' })
    expect(selected()?.getAttribute('data-row-index')).toBe(String(today - 1))
  })

  it('open the item under the selection (Enter), not one shifted by the headings above it', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const today = shown().filter((item) => Date.parse(item.published_at ?? '') >= startOfToday).length
    for (let press = 0; press <= today; press += 1) fireEvent.keyDown(window, { key: 'j' })
    const wanted = document.querySelector('.r-feedrow.is-selected .r-feedrow__headline')?.textContent
    fireEvent.keyDown(window, { key: 'Enter' })
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/item\/\d+$/))
    const id = Number(window.location.hash.split('/').pop())
    expect(mockState().items.find((item) => item.id === id)?.headline).toBe(wanted)
  })

  it('count only what is loaded and leave the last day’s count off while more pages remain', async () => {
    // Enough items for a second page, so the last day could still grow.
    const base = mockState().items[0]
    const extra = Array.from({ length: 60 }, (_, index) => ({ ...base, id: 500 + index, headline: `Extra ${index}`, title: `Extra ${index}`, published_at: new Date(2026, 10, 12, 14, 0, 60 - index).toISOString() }))
    mockState().items.push(...extra)
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    expect(headings()).toHaveLength(1)
    expect(headings()[0].textContent).toBe('Today') // no count while the day is still loading
  })
})

describe('where the headings do not appear', () => {
  it('leaves them out of a list of items close to some text', async () => {
    window.history.replaceState(null, '', '/#/feed?related=aster')
    render(<RoutedFeed />)
    await screen.findByText('Related to: aster')
    await waitFor(() => expect(document.querySelectorAll('.r-feedrow').length).toBeGreaterThan(0))
    expect(headings()).toHaveLength(0)
  })

  it('leaves them out of the items an assistant answer cited', async () => {
    window.history.replaceState(null, '', '/#/feed?cited=101,102,103')
    render(<RoutedFeed />)
    await waitFor(() => expect(document.querySelectorAll('.r-feedrow')).toHaveLength(3))
    expect(headings()).toHaveLength(0)
  })

  it('leaves them out of Missed, which is ordered by score', async () => {
    window.history.replaceState(null, '', '/#/feed?missed=true')
    render(<RoutedFeed />)
    await waitFor(() => expect(document.querySelectorAll('.r-feedrow').length).toBeGreaterThan(0))
    expect(headings()).toHaveLength(0)
  })

  it('keep them in a search, which the service still lists by date', async () => {
    window.history.replaceState(null, '', '/#/feed?q=aster')
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
  })
})

describe('positions', () => {
  it('keep every row in place when the Feed is hidden under the reader and shown again', async () => {
    const view = render(<RoutedFeed active />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const before = [...document.querySelectorAll('.r-feed > li')]
    view.rerender(<RoutedFeed active={false} />)
    await act(async () => undefined)
    view.rerender(<RoutedFeed active />)
    await act(async () => undefined)
    await waitFor(() => expect(document.querySelectorAll('.r-feed > li')).toHaveLength(before.length))
    // The same DOM nodes: nothing was rebuilt, so the scroll offset still points at the same item.
    expect([...document.querySelectorAll('.r-feed > li')].every((node, index) => node === before[index])).toBe(true)
  })

  it('number rows by item, so a remembered selection means the same item with or without headings', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headings().length).toBeGreaterThan(0))
    const indexes = [...document.querySelectorAll('.r-feedrow')].map((node) => node.getAttribute('data-row-index'))
    expect(indexes).toEqual(indexes.map((_, index) => String(index)))
  })
})
