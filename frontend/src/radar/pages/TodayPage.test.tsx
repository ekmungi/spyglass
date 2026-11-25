// Tests for Today: rendering the brief from the sample fixture (section order, empty sections
// omitted, caught-up marker), opening the reader, the no-brief Compose now flow, the line about
// unjudged items at the end, the reading list, and a brief composed before unpicked stories existed.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import type { BriefDoc, BriefSection, TodayResponse } from '../api/types'
import { clearResourceCache, STALE_AFTER_MS } from '../hooks/useResource'
import { buildBrief } from '../mock/brief'
import { buildItems } from '../mock/items'
import { resetItemState } from '../state/itemState'
import { resetReadingList, useReadingList } from '../state/readingList'
import { orderedSections, sectionTitle } from '../today/sections'
import { TodayPage } from './TodayPage'

/** Shows the current reading list as JSON, so a test can read what Today set. */
function ReadingListProbe() {
  return <output data-testid="reading-list">{JSON.stringify(useReadingList())}</output>
}

/** A section as a brief composed before unpicked stories were stored has it: no `more`, no `pool`. */
function withoutUnpicked({ key, title, note, stories }: BriefSection): BriefSection {
  return { key, title, note, stories }
}

const DAY = '2026-11-12'

/** Serve /today (and /briefs/generate) from the given values; `today` may be a function for changing answers. */
function serve(today: TodayResponse | (() => TodayResponse), generated?: BriefDoc): string[] {
  const calls: string[] = []
  setFetchForTesting(async (url, init) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.endsWith('/today')) return new Response(JSON.stringify(typeof today === 'function' ? today() : today), { status: 200 })
    if (url.endsWith('/briefs/generate') && generated) return new Response(JSON.stringify(generated), { status: 200 })
    if (url.endsWith('/profile')) return new Response(JSON.stringify({ sections: [] }), { status: 200 })
    return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
  })
  return calls
}

beforeEach(() => {
  clearResourceCache()
  resetItemState()
  resetReadingList()
  window.history.replaceState(null, '', '/#/today')
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('TodayPage', () => {
  it('renders the sections in the fixed order with the caught-up marker', async () => {
    const brief = buildBrief(buildItems(), DAY)
    serve({ brief, days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    const headings = screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)
    expect(headings).toEqual(['Top stories', 'On your watch list', 'Worth knowing', 'Papers', 'From you', 'Skim'])
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/12 November/)
    const marker = screen.getByTestId('caught-up')
    expect(within(marker).getByText('You are caught up.')).toBeInTheDocument()
    expect(marker.textContent).toContain('179 other items were filtered out')
    expect(within(marker).getByRole('link').getAttribute('href')).toBe('#/feed?tier=all')
  })

  it('omits empty sections and sorts sections the document lists out of order', async () => {
    const full = buildBrief(buildItems(), DAY)
    const reordered: BriefDoc = {
      ...full,
      sections: [...full.sections].reverse().map((section) => (section.key === 'watch' ? { ...section, stories: [] } : section)),
    }
    expect(orderedSections(reordered).map((section) => section.key)).toEqual(['top', 'notable', 'papers', 'from_you', 'skim'])
    serve({ brief: reordered, days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    expect(screen.queryByText('On your watch list')).toBeNull()
  })

  it('uses the document\'s own section title and falls back to a default when it is missing', async () => {
    const full = buildBrief(buildItems(), DAY)
    const retitled: BriefDoc = { ...full, sections: full.sections.map((s) => (s.key === 'top' ? { ...s, title: 'The big ones' } : s.key === 'notable' ? { ...s, title: '' } : s)) }
    serve({ brief: retitled, days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('The big ones')
    expect(screen.getByRole('heading', { level: 2, name: 'Worth knowing' })).toBeInTheDocument()
    expect(sectionTitle({ key: 'watch', title: '' })).toBe('On your watch list')
  })

  it('names the watched organisation on watch rows only', async () => {
    serve({ brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    expect(screen.getByText('Endovista · Imaging AI')).toBeInTheDocument()
    expect(screen.getByText('Lucent Scope · Imaging AI')).toBeInTheDocument()
    expect(document.querySelectorAll('.r-story__watch')).toHaveLength(2)
    expect(document.querySelectorAll('.r-story--top .r-story__watch')).toHaveLength(0)
  })

  it('does not show a stale "no brief yet" answer once a brief exists (revalidates on entry)', async () => {
    let answer: TodayResponse = { brief: null, days: [], status: {} }
    serve(() => answer)
    const first = render(<TodayPage />)
    await screen.findByRole('button', { name: 'Compose now' })
    first.unmount()

    // A brief is composed elsewhere; entering Today again must pick it up without a reload.
    answer = { brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} }
    render(<TodayPage />)
    expect(screen.queryByRole('button', { name: 'Compose now' })).toBeNull() // no flash of the stale empty state
    expect(await screen.findByText('Top stories')).toBeInTheDocument()
  })

  it('keeps the same elements on screen when the refreshed answer is identical (no flicker)', async () => {
    const answer: TodayResponse = { brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} }
    const calls = serve(() => JSON.parse(JSON.stringify(answer)))
    const first = render(<TodayPage />)
    await screen.findByText('Top stories')
    first.unmount()
    render(<TodayPage />)
    const heading = screen.getByText('Top stories') // cached copy is there at once
    await waitFor(() => expect(calls.filter((call) => call.endsWith('/today')).length).toBe(2))
    await act(async () => undefined)
    expect(screen.getByText('Top stories')).toBe(heading)
  })

  it('refreshes when the window regains focus after the answer has gone stale', async () => {
    let answer: TodayResponse = { brief: null, days: [], status: {} }
    serve(() => answer)
    render(<TodayPage />)
    await screen.findByRole('button', { name: 'Compose now' })
    answer = { brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} }
    const now = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(now + STALE_AFTER_MS + 1000)
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(await screen.findByText('Top stories')).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('refreshes when it becomes the visible page again after the reader', async () => {
    let answer: TodayResponse = { brief: null, days: [], status: {} }
    const calls = serve(() => answer)
    const view = render(<TodayPage active />)
    await screen.findByRole('button', { name: 'Compose now' })
    view.rerender(<TodayPage active={false} />)
    answer = { brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} }
    view.rerender(<TodayPage active />)
    expect(await screen.findByText('Top stories')).toBeInTheDocument()
    expect(calls.filter((call) => call.endsWith('/today')).length).toBe(2)
  })

  it('shows the meta line and the sources of a story', async () => {
    serve({ brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    expect(screen.getByText(/6 min read · 33 stories from 212 collected/)).toBeInTheDocument()
    expect(screen.getByText(/Signal Ledger · Open Weights Weekly · \+3/)).toBeInTheDocument()
    expect(screen.getAllByText('Sent by you from Slack').length).toBe(1)
  })

  it('opens the reader route when a story is clicked', async () => {
    serve({ brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} })
    render(<TodayPage />)
    const headline = await screen.findByText(/Aster AI releases Aster 4/)
    fireEvent.click(headline.closest('a') as HTMLAnchorElement)
    expect(window.location.hash).toBe('#/item/101')
  })

  it('opens the selected story with j and Enter', async () => {
    serve({ brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(document.body, { key: 'Enter' })
    expect(window.location.hash).toBe('#/item/104')
  })

  it('walks onto the next page of a section with j and opens the story there with Enter', async () => {
    serve({ brief: buildBrief(buildItems(), DAY), days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    expect(screen.getByText('1-5 of 6')).toBeInTheDocument()
    for (let press = 0; press < 6; press += 1) fireEvent.keyDown(window, { key: 'j' })
    expect(screen.getByText('6-6 of 6')).toBeInTheDocument()
    fireEvent.keyDown(document.body, { key: 'Enter' })
    expect(window.location.hash).toBe('#/item/143')
  })

  it('puts the line about unjudged items at the end of the article, not in the masthead', async () => {
    const notice = "40 collected items are still waiting to be judged, so a story may be missing from today's selection."
    serve({ brief: { ...buildBrief(buildItems(), DAY), degraded: true, unjudged: 40, notice }, days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    const article = document.querySelector('article.r-brief') as HTMLElement
    expect(article.lastElementChild?.textContent).toBe(notice)
    expect(document.querySelector('.r-masthead')?.textContent).not.toContain(notice)
    expect(screen.getAllByText(notice)).toHaveLength(1)
  })

  it('sets the reading list to Today with every story, picked before unpicked within each section', async () => {
    const brief = buildBrief(buildItems(), DAY)
    serve({ brief, days: [DAY], status: {} })
    render(
      <>
        <TodayPage />
        <ReadingListProbe />
      </>,
    )
    await screen.findByText('Top stories')
    const list = JSON.parse(screen.getByTestId('reading-list').textContent ?? 'null')
    const expected = orderedSections(brief).flatMap((section) => [...section.stories, ...(section.more ?? [])]).map((story) => story.item_id)
    expect(list.label).toBe('Today')
    expect(list.origin).toBe('today')
    expect(list.ids).toEqual(expected)
    // The top section's three picked stories, its three unpicked ones, then the watch list.
    expect(list.ids.slice(0, 8)).toEqual([101, 104, 103, 141, 142, 143, 102, 117])
  })

  it('shows a brief composed before unpicked stories were stored, with every story and no arrows', async () => {
    const full = buildBrief(buildItems(), DAY)
    const older: BriefDoc = { ...full, sections: full.sections.map(withoutUnpicked) }
    serve({ brief: older, days: [DAY], status: {} })
    render(<TodayPage />)
    await screen.findByText('Top stories')
    const notable = document.querySelector('.r-brief__section--notable') as HTMLElement
    expect(within(notable).getAllByRole('listitem')).toHaveLength(8)
    expect(screen.queryAllByRole('button', { name: 'More stories in this section' })).toHaveLength(0)
    expect(screen.queryByText('The brief could not be loaded')).toBeNull()
  })

  it('offers Compose now when there is no brief, then shows the composed brief', async () => {
    const calls = serve({ brief: null, days: [], status: {} }, buildBrief(buildItems(), DAY))
    render(<TodayPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Compose now' }))
    expect(await screen.findByText('Top stories')).toBeInTheDocument()
    expect(calls).toContain('POST /api/radar/briefs/generate')
  })

  it('explains a failed load and offers to try again', async () => {
    setFetchForTesting(async () => new Response('{}', { status: 503 }))
    render(<TodayPage />)
    expect(await screen.findByText('The brief could not be loaded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
