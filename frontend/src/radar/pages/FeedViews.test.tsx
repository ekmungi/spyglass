// The Feed's two saved views: "Missed" (what the reader has not opened, saved or filed from the last
// 7 days, by score) and one Watch group's items (the ones the Watch page counts for the group).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearFeedCache } from '../feed/useFeed'
import { clearMissedCount } from '../feed/useMissedCount'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { groupWatch } from '../mock/catalog'
import { mockState, patchItemState } from '../mock/store'
import { useRoute } from '../router'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { resetItemState } from '../state/itemState'
import { FeedPage } from './FeedPage'

/** The Feed as the app mounts it: its parameters come from the address. */
function RoutedFeed() {
  const route = useRoute()
  return <FeedPage params={route.name === 'feed' ? route.params : {}} />
}

beforeEach(() => {
  resetMockState()
  resetItemState()
  clearResourceCache()
  clearFeedCache()
  clearMissedCount()
  window.history.replaceState(null, '', '/#/feed')
  resetFilingConfigured()
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  resetFilingConfigured()
})

const headlines = () => [...document.querySelectorAll('.r-feedrow__headline')].map((node) => node.textContent ?? '')
const idsOf = (list: string[]) => list.map((line) => mockState().items.find((item) => item.headline === line)?.id)

/** The sample items Missed should list: top or notable, unseen, in score order. */
function expectedMissed() {
  return mockState()
    .items.filter((item) => (item.tier === 'top' || item.tier === 'notable') && !item.state.opened && !item.state.saved && !item.state.from_user)
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || (b.published_at ?? '').localeCompare(a.published_at ?? ''))
}

describe('Missed', () => {
  it('sits beside To file (shown only where filing is set up) and carries the number of missed items', async () => {
    setFilingConfigured(true)
    render(<RoutedFeed />)
    await screen.findByRole('button', { name: /^To file/ })
    const chip = await screen.findByRole('button', { name: /^Missed/ })
    await waitFor(() => expect(chip).toHaveTextContent(`Missed${expectedMissed().length}`))
    const names = screen.getAllByRole('button').map((button) => button.textContent ?? '')
    expect(names[names.findIndex((name) => name.startsWith('To file')) + 1]).toMatch(/^Missed/)
  })

  it('puts missed=true in the address and lists the unseen top and notable items by score', async () => {
    render(<RoutedFeed />)
    fireEvent.click(await screen.findByRole('button', { name: /^Missed/ }))
    expect(window.location.hash).toBe('#/feed?missed=true')
    expect(screen.getByRole('button', { name: /^Missed/ })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    expect(idsOf(headlines())).toEqual(expectedMissed().map((item) => item.id))
    fireEvent.click(screen.getByRole('button', { name: /^Missed/ }))
    expect(window.location.hash).toBe('#/feed')
  })

  it('leaves out what was opened, saved or sent in', async () => {
    patchItemState(101, { opened: true })
    patchItemState(102, { saved: true })
    render(<RoutedFeed />)
    fireEvent.click(await screen.findByRole('button', { name: /^Missed/ }))
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    const ids = idsOf(headlines())
    expect(ids).not.toContain(101)
    expect(ids).not.toContain(102)
    expect(ids.every((id) => mockState().items.find((item) => item.id === id)?.state.from_user === false)).toBe(true)
  })

  it('keeps an item you opened where it is when you come back, and drops it at the next load', async () => {
    const view = render(<FeedPage params={{ missed: 'true' }} active />)
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    const first = expectedMissed()[0]
    const before = [...document.querySelectorAll('.r-feedrow')]
    const count = expectedMissed().length
    await waitFor(() => expect(screen.getByRole('button', { name: /^Missed/ })).toHaveTextContent(`Missed${count}`))

    // Opening: the row is marked read and the reader covers the Feed (the page is inactive under it).
    fireEvent.click(within(before[0] as HTMLElement).getByRole('link', { name: first.headline }))
    view.rerender(<FeedPage params={{ missed: 'true' }} active={false} />)
    // The reader (not the row) tells the service it was opened; the sample service learns it the same way.
    patchItemState(first.id, { opened: true })
    view.rerender(<FeedPage params={{ missed: 'true' }} active />)
    await act(async () => undefined)

    // Back from the reader: the same rows, the opened one dimmed in place, the number on the chip lower.
    const after = [...document.querySelectorAll('.r-feedrow')]
    expect(after).toHaveLength(before.length)
    expect(after.every((node, index) => node === before[index])).toBe(true)
    expect(after[0]).toHaveClass('is-read')
    await waitFor(() => expect(screen.getByRole('button', { name: /^Missed/ })).toHaveTextContent(`Missed${count - 1}`))

    // A fresh visit loads the list again, and the opened item is gone.
    view.unmount()
    clearFeedCache()
    render(<FeedPage params={{ missed: 'true' }} active />)
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    expect(idsOf(headlines())).toEqual(expectedMissed().map((item) => item.id))
    expect(idsOf(headlines())).not.toContain(first.id)
  })

  it('says there is nothing missed when everything was seen', async () => {
    for (const item of mockState().items) patchItemState(item.id, { opened: true })
    render(<FeedPage params={{ missed: 'true' }} />)
    expect(await screen.findByText('Nothing missed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Missed' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('a Watch group in the Feed', () => {
  const groupName = 'AI labs'
  const weekCount = () => groupWatch(mockState().watch, mockState().items).categories.find((category) => category.name === groupName)?.week_count

  it('shows a chip "Watch: AI labs" with Clear, and lists as many items as the Watch page counts', async () => {
    window.history.replaceState(null, '', `/#/feed?watch_group=${encodeURIComponent(groupName)}`)
    render(<RoutedFeed />)
    expect(await screen.findByText(`Watch: ${groupName}`)).toBeInTheDocument()
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    expect(weekCount()).toBeGreaterThan(0)
    expect(headlines()).toHaveLength(weekCount() as number)
    expect(document.querySelector('.r-page-meta')).toHaveTextContent(`${weekCount()} items`)
  })

  it('goes back to the whole feed on Clear, keeping other filters', async () => {
    window.history.replaceState(null, '', `/#/feed?watch_group=${encodeURIComponent(groupName)}&saved=true`)
    render(<RoutedFeed />)
    await screen.findByText(`Watch: ${groupName}`)
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(window.location.hash).toBe('#/feed?saved=true')
    expect(screen.queryByText(/^Watch:/)).toBeNull()
  })

  it('gives an empty list, not an error, for a group that does not exist', async () => {
    render(<FeedPage params={{ watch_group: 'No such group' }} />)
    expect(await screen.findByText('Nothing from this group this week')).toBeInTheDocument()
    expect(screen.queryByText(/could not be loaded/)).toBeNull()
  })

  it('keeps its date headings, because the list is in time order', async () => {
    render(<FeedPage params={{ watch_group: groupName }} />)
    await waitFor(() => expect(document.querySelectorAll('.r-feed-day').length).toBeGreaterThan(0))
  })
})
