// Tests for the Feed page: the search box (a click on Feed in the rail must not bring the last search back),
// the toolbar (search, Ask, Filters, the views strip and the sections strip) and the reading list.
import { cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { resetReadingList, useReadingList } from '../state/readingList'
import { FeedPage } from './FeedPage'

beforeEach(() => {
  resetMockState()
  clearResourceCache()
  clearFeedCache()
  window.history.replaceState(null, '', '/#/feed')
  resetFilingConfigured()
  resetReadingList()
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  resetFilingConfigured()
  resetReadingList()
})

describe('FeedPage search', () => {
  it('shows the search from the address, and clears the box when the address loses it', async () => {
    const { rerender } = render(<FeedPage params={{ q: 'robot' }} />)
    const box = (await screen.findByPlaceholderText(/Search titles/)) as HTMLInputElement
    expect(box.value).toBe('robot')
    rerender(<FeedPage params={{}} />)
    expect(box.value).toBe('')
    // The old search must not be written back into the address after the delay.
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(window.location.hash).toBe('#/feed')
    expect(box.value).toBe('')
  })

  it('writes what the reader types into the address once typing settles', async () => {
    render(<FeedPage params={{}} />)
    const box = await screen.findByPlaceholderText(/Search titles/)
    fireEvent.change(box, { target: { value: 'polyp' } })
    await waitFor(() => expect(window.location.hash).toBe('#/feed?q=polyp'), { timeout: 2000 })
  })
})

describe('FeedPage Filed filter', () => {
  it('has "Filed" in the Filters menu; choosing it puts filed=true in the address and shows only filed items', async () => {
    render(<FeedPage params={{}} />)
    await screen.findByPlaceholderText(/Search titles/)
    fireEvent.click(screen.getByRole('button', { name: /Filters/ }))
    expect(screen.getByRole('menuitem', { name: 'Filed' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Filed' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed?filed=true'))
  })

  it('sends filed=true to the service and shows whatever comes back', async () => {
    window.history.replaceState(null, '', '/#/feed?filed=true')
    render(<FeedPage params={{ filed: 'true' }} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Filters (1)' })).toBeInTheDocument())
    // The sample service filters on `filed`; one sample item starts out filed.
    expect(await screen.findByText('Notes from a talk on post-market surveillance for AI devices', {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('Aster AI releases Aster 4 with a million-token context window')).not.toBeInTheDocument()
  })
})

/** The text of each tab in a strip, without the small count after the label. */
const labels = (strip: HTMLElement) => within(strip).getAllByRole('tab').map((tab) => (tab.textContent ?? '').replace(/\s*\d+$/, ''))

describe('FeedPage toolbar', () => {
  it('holds the search field, an Ask button and a Filters button, and no Related control', async () => {
    render(<FeedPage params={{}} />)
    await screen.findByPlaceholderText(/Search titles/)
    expect(screen.getByRole('button', { name: 'Ask your feed (opens the assistant)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filters' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Related/ })).toBeNull()
    expect(screen.queryByRole('tab', { name: /Related/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    const menu = screen.getByRole('menu', { name: 'More filters' })
    for (const name of ['All kinds', 'News', 'Releases', 'Research', 'Papers', 'Posts', 'Videos', 'Regulatory', 'Tools', 'Opinion', 'Show filtered-out items', 'Filed']) {
      // A chosen entry carries the word "selected" after its label.
      expect(within(menu).getByRole('menuitem', { name: new RegExp(`^${name}(selected)?$`) })).toBeInTheDocument()
    }
  })

  it('has a views strip with Everything, Missed, Saved and From you, and To file only where filing is set up', async () => {
    render(<FeedPage params={{}} />)
    const views = await screen.findByRole('tablist', { name: 'Views' })
    expect(labels(views)).toEqual(['Everything', 'Missed', 'Saved', 'From you'])
    expect(within(views).getByRole('tab', { name: 'Everything' })).toHaveAttribute('aria-selected', 'true')
    cleanup()
    setFilingConfigured(true)
    render(<FeedPage params={{}} />)
    const withFiling = await screen.findByRole('tablist', { name: 'Views' })
    await waitFor(() => expect(labels(withFiling)).toEqual(['Everything', 'Missed', 'Saved', 'From you', 'To file']))
  })

  it('shows the number of missed items on the Missed tab', async () => {
    render(<FeedPage params={{}} />)
    const missed = await screen.findByRole('tab', { name: /^Missed/ })
    await waitFor(() => expect(missed.textContent).toMatch(/^Missed\s*\d+$/))
  })

  it('explains the Missed view in its tooltip', async () => {
    render(<FeedPage params={{}} />)
    expect(await screen.findByRole('tab', { name: /^Missed/ })).toHaveAttribute('title', 'Top and notable items from the last 7 days that you have not opened, saved or filed')
  })

  it('puts the same parameter in the address as the old chip when Saved is chosen, and clears the views on Everything', async () => {
    render(<FeedPage params={{}} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Saved' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed?saved=true'))
    fireEvent.click(screen.getByRole('tab', { name: 'Everything' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed'))
  })

  it('makes the views exclusive: choosing one drops the parameters of the others but keeps other filters', async () => {
    window.history.replaceState(null, '', '/#/feed?saved=true&section=health&kind=paper')
    render(<FeedPage params={{ saved: 'true', section: 'health', kind: 'paper' }} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'From you' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed?section=health&kind=paper&from_user=true'))
    expect(window.location.hash).not.toContain('saved')
  })

  it('shows the first view parameter in the order Missed, Saved, From you as selected when an old link carries several', async () => {
    render(<FeedPage params={{ saved: 'true', from_user: 'true' }} />)
    expect(await screen.findByRole('tab', { name: 'Saved' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'From you' })).toHaveAttribute('aria-selected', 'false')
    cleanup()
    render(<FeedPage params={{ saved: 'true', missed: 'true' }} />)
    expect(await screen.findByRole('tab', { name: /^Missed/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('has a sections strip that sets the section parameter, and clears it on All sections', async () => {
    render(<FeedPage params={{}} />)
    const sections = await screen.findByRole('tablist', { name: 'Sections' })
    expect(within(sections).getByRole('tab', { name: 'All sections' })).toHaveAttribute('aria-selected', 'true')
    const tabs = within(sections).getAllByRole('tab')
    expect(tabs.length).toBeGreaterThan(1)
    fireEvent.click(tabs[1])
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/feed\?section=/))
    fireEvent.click(within(sections).getByRole('tab', { name: 'All sections' }))
    await waitFor(() => expect(window.location.hash).toBe('#/feed'))
  })

  it('still shows the focused list for an address with related text, and keeps the text in the box', async () => {
    window.history.replaceState(null, '', '/#/feed?related=aster')
    render(<FeedPage params={{ related: 'aster' }} />)
    expect(await screen.findByText('Related to: aster')).toBeInTheDocument()
    expect((screen.getByPlaceholderText(/Search titles/) as HTMLInputElement).value).toBe('aster')
    await waitFor(() => expect(document.querySelectorAll('.r-feedrow').length).toBeGreaterThan(0))
  })
})

describe('FeedPage reading list', () => {
  it('sets the reading list to the Feed, with the loaded rows in order, when an item is opened', async () => {
    render(<FeedPage params={{}} />)
    await waitFor(() => expect(document.querySelectorAll('.r-feedrow').length).toBeGreaterThan(1))
    const links = [...document.querySelectorAll('.r-feedrow a[href]')]
    const ids = links.map((link) => Number(/item\/(\d+)/.exec(link.getAttribute('href') ?? '')?.[1]))
    const { result } = renderHook(() => useReadingList())
    expect(result.current).toBeNull()
    fireEvent.click(links[1])
    expect(result.current).toEqual({ label: 'the Feed', ids })
  })
})
