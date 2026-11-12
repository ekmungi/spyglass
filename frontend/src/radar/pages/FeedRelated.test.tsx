// The Feed's ways of showing a hand-picked list: the "Related" toggle (a search by meaning), the
// neighbours of one item, and the items an assistant answer cited. Each is carried in the address.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { getAssistState, setAssistOpen } from '../assistant/assistStore'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { mockState } from '../mock/store'
import { useRoute } from '../router'
import { FeedPage } from './FeedPage'

/** The Feed as the app mounts it: its parameters come from the address, so Back and Clear work. */
function RoutedFeed() {
  const route = useRoute()
  return <FeedPage params={route.name === 'feed' ? route.params : {}} />
}

beforeEach(() => {
  resetMockState()
  clearResourceCache()
  clearFeedCache()
  window.history.replaceState(null, '', '/#/feed')
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

/** The headlines of the rows on screen, in order. */
function headlines(): string[] {
  return [...document.querySelectorAll('.r-feedrow__headline')].map((node) => node.textContent ?? '')
}

const headlineOf = (id: number) => mockState().items.find((item) => item.id === id)?.headline ?? ''

describe('Feed "Related" toggle', () => {
  it('moves the typed text to the address as related=, shows the closest items and a chip with Clear', async () => {
    render(<RoutedFeed />)
    const box = await screen.findByPlaceholderText(/Search titles/)
    fireEvent.change(box, { target: { value: 'aster' } })
    await waitFor(() => expect(window.location.hash).toBe('#/feed?q=aster'), { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: 'Related' }))
    expect(window.location.hash).toBe('#/feed?related=aster')
    expect(screen.getByRole('button', { name: 'Related' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText('Related to: aster')).toBeInTheDocument()
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    expect(headlines().some((line) => /aster/i.test(line))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(window.location.hash).toBe('#/feed')
    expect(screen.queryByText(/Related to:/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Related' })).toHaveAttribute('aria-pressed', 'false')
    expect((await screen.findByPlaceholderText(/Search titles/)) as HTMLInputElement).toHaveValue('')
  })

  it('sends typed text as related= (debounced) while on, and hands it back to the plain search when turned off', async () => {
    render(<RoutedFeed />)
    fireEvent.click(await screen.findByRole('button', { name: 'Related' }))
    const box = screen.getByPlaceholderText(/Describe a topic/)
    fireEvent.change(box, { target: { value: 'polyp detection' } })
    await waitFor(() => expect(window.location.hash).toBe('#/feed?related=polyp+detection'), { timeout: 2000 })
    expect(await screen.findByText('Related to: polyp detection')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Related' }))
    expect(window.location.hash).toBe('#/feed?q=polyp+detection')
    expect(screen.queryByText(/Related to:/)).not.toBeInTheDocument()
  })

  it('says so when nothing is close', async () => {
    window.history.replaceState(null, '', '/#/feed?related=zzzxqj')
    render(<RoutedFeed />)
    expect(await screen.findByText('Nothing in your feed is close to that', {}, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe('Feed list from one item', () => {
  it('shows the neighbours of the item, not the item, under a chip naming it', async () => {
    window.history.replaceState(null, '', '/#/feed?related_item=101')
    render(<RoutedFeed />)
    expect(await screen.findByText(`Related to: ${headlineOf(101)}`, {}, { timeout: 4000 })).toBeInTheDocument()
    await waitFor(() => expect(headlines().length).toBeGreaterThan(0))
    expect(headlines()).not.toContain(headlineOf(101))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(window.location.hash).toBe('#/feed')
  })
})

describe('Feed list from an assistant answer', () => {
  it('shows exactly the cited items in the cited order, with the chip "From the assistant\'s answer"', async () => {
    window.history.replaceState(null, '', '/#/feed?cited=103%2C101')
    render(<RoutedFeed />)
    expect(await screen.findByText("From the assistant's answer", {}, { timeout: 4000 })).toBeInTheDocument()
    await waitFor(() => expect(headlines()).toEqual([headlineOf(103), headlineOf(101)]))
    expect(screen.getByText('2 items')).toBeInTheDocument()
    fireEvent.click(within(document.querySelector('.r-feed-focus') as HTMLElement).getByRole('button', { name: 'Clear' }))
    expect(window.location.hash).toBe('#/feed')
  })

  it('ignores a malformed list in the address and shows the whole feed', async () => {
    render(<RoutedFeed />)
    await waitFor(() => expect(headlines().length).toBeGreaterThan(5), { timeout: 4000 })
    expect(screen.queryByText("From the assistant's answer")).not.toBeInTheDocument()
  })
})

describe('Assistant on the Feed', () => {
  it('points the panel at the feed, and "Ask your feed" opens it', async () => {
    setAssistOpen('feed', false)
    render(<RoutedFeed />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ask your feed' }))
    expect(getAssistState().target).toEqual({ kind: 'feed' })
    expect(getAssistState().open.feed).toBe(true)
    setAssistOpen('feed', false)
  })
})
