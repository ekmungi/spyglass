// Tests for the workspace: panes, relevance hide-filter, FTS search, chips, bulk actions.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'
import { WorkspaceView } from './WorkspaceView'

// virtua needs real layout (absent in jsdom); render its children directly so the list
// rows are present for these behavioral assertions. Real virtualization is verified in-browser.
vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const cards = [
  makeCard({ id: 1, title: 'First card', relevance: 'high', effective_relevance: 'high', category: 'Agentic AI' }),
  makeCard({ id: 2, title: 'Second card', relevance: 'medium', effective_relevance: 'medium', category: 'Healthcare AI' }),
  makeCard({
    id: 3,
    title: 'Low card',
    relevance: 'low',
    effective_relevance: 'low',
    relevance_reason: 'too introductory',
    category: 'Agentic AI',
  }),
  makeCard({
    id: 4,
    title: 'Unjudged card',
    relevance: null,
    effective_relevance: null,
    category: 'Agentic AI',
  }),
]

const categories = [
  { name: 'Agentic AI', count: 3 },
  { name: 'Healthcare AI', count: 1 },
]

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
    if (url.includes('/fulltext')) return respond({ status: 'ok', markdown: 'Stored text.' })
    if (url.includes('/api/categories')) return respond(categories)
    if (url.includes('/api/search')) {
      return respond([{ ...cards[1], snippet: 'about [memory] systems' }])
    }
    if (url.includes('/relevance') && init?.method === 'PATCH') {
      return respond({ relevance: 'high', relevance_override: true })
    }
    if (url.includes('/category') && init?.method === 'PATCH') {
      return respond({ category: 'Agentic AI', category_override: true })
    }
    if (url.includes('/feedback') && init?.method === 'PATCH') {
      // The feedback endpoint returns the FULL updated card.
      return respond({ ...cards[0], feedback: 'up' })
    }
    return respond({})
  })
}

function renderView(overrides: Partial<Parameters<typeof WorkspaceView>[0]> = {}) {
  return render(
    <WorkspaceView
      cards={cards}
      refreshing={false}
      onRefresh={() => {}}
      onOpenClaude={() => {}}
      onUpdate={() => {}}
      onMerge={() => {}}
      onDelete={() => {}}
      onOpenExternal={() => {}}
      onReload={() => {}}
      {...overrides}
    />,
  )
}

describe('WorkspaceView', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
    vi.stubGlobal('fetch', stubFetch())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders rows and opens the reader on click', async () => {
    renderView()
    fireEvent.click(screen.getByText('Second card'))
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
  })

  it('opens an externally requested card and reports it handled once', async () => {
    const onCardRequestHandled = vi.fn()
    renderView({ openCardRequest: 2, onCardRequestHandled })
    // The reader opens card 2 without any click (brief card: link routing).
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
    await waitFor(() => expect(onCardRequestHandled).toHaveBeenCalledTimes(1))
  })

  it('an external card request clears hiding filters so the requested card shows', async () => {
    vi.stubGlobal('scrollTo', vi.fn())
    const onCardRequestHandled = vi.fn()
    const { rerender } = renderView()
    // Hide everything below medium: the low card (id 3) leaves the list.
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'medium' },
    })
    expect(screen.queryByText('Low card')).not.toBeInTheDocument()
    // A brief's card: link now requests the hidden card -> the request wins over the filter.
    rerender(
      <WorkspaceView
        cards={cards}
        refreshing={false}
        onRefresh={() => {}}
        onOpenClaude={() => {}}
        onUpdate={() => {}}
        onMerge={() => {}}
        onDelete={() => {}}
        onOpenExternal={() => {}}
        onReload={() => {}}
        openCardRequest={3}
        onCardRequestHandled={onCardRequestHandled}
      />,
    )
    // The card is visible again (list + reader) and the request was acknowledged.
    expect(await screen.findAllByText('Low card')).not.toHaveLength(0)
    await waitFor(() => expect(onCardRequestHandled).toHaveBeenCalled())
  })

  it('default relevance filter "all" shows every card', () => {
    renderView()
    // All four cards should be visible with the default 'all' filter
    expect(screen.getByText('First card')).toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()
    expect(screen.getByText('Low card')).toBeInTheDocument()
    expect(screen.getByText('Unjudged card')).toBeInTheDocument()
  })

  it('the "unjudged" filter shows only cards with null effective_relevance', () => {
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'unjudged' },
    })
    expect(screen.queryByText('First card')).not.toBeInTheDocument()
    expect(screen.queryByText('Second card')).not.toBeInTheDocument()
    expect(screen.queryByText('Low card')).not.toBeInTheDocument()
    expect(screen.getByText('Unjudged card')).toBeInTheDocument()
  })

  it('a level filter hides cards below the rank and hides null/out', () => {
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'medium' },
    })
    // high and medium pass; low, out, and null do not
    expect(screen.getByText('First card')).toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()
    expect(screen.queryByText('Low card')).not.toBeInTheDocument()
    expect(screen.queryByText('Unjudged card')).not.toBeInTheDocument()
  })

  it('changing the relevance filter resets the window scroll to the top', () => {
    const scrollSpy = vi.fn()
    vi.stubGlobal('scrollTo', scrollSpy)
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'low' },
    })
    expect(scrollSpy).toHaveBeenCalledWith(0, 0)
  })

  it("changing the relevance filter resets the list pane's own scroll", () => {
    vi.stubGlobal('scrollTo', vi.fn())
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    const pane = screen.getByTestId('list-pane')
    pane.scrollTop = 500
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'low' },
    })
    expect(pane.scrollTop).toBe(0)
  })

  it('changing a facet filter resets the window scroll to the top', () => {
    const scrollSpy = vi.fn()
    vi.stubGlobal('scrollTo', scrollSpy)
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Category' }), {
      target: { value: 'Agentic AI' },
    })
    expect(scrollSpy).toHaveBeenCalledWith(0, 0)
  })

  it('selecting a category chip resets the window scroll to the top', async () => {
    const scrollSpy = vi.fn()
    vi.stubGlobal('scrollTo', scrollSpy)
    renderView()
    fireEvent.click(await screen.findByRole('button', { name: /Healthcare AI/ }))
    expect(scrollSpy).toHaveBeenCalledWith(0, 0)
  })

  it('sorting by "Recently published" reorders the list by published date', () => {
    vi.stubGlobal('scrollTo', vi.fn())
    const now = Date.now()
    const dated = [
      // Served order = collected order: newest arrival first, but IT was published oldest.
      makeCard({ id: 31, title: 'Arrived first published last', created_at: new Date(now).toISOString(), published_at: new Date(now - 3 * 86400_000).toISOString() }),
      makeCard({ id: 32, title: 'Fresh publish', created_at: new Date(now - 86400_000).toISOString(), published_at: new Date(now - 3600_000).toISOString() }),
    ]
    renderView({ cards: dated })
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort' }), {
      target: { value: 'published' },
    })
    const titles = screen.getAllByText(/Arrived first published last|Fresh publish/).map((el) => el.textContent)
    expect(titles).toEqual(['Fresh publish', 'Arrived first published last'])
  })

  it('persists the sort choice to localStorage and resets scroll on change', () => {
    const scrollSpy = vi.fn()
    vi.stubGlobal('scrollTo', scrollSpy)
    renderView()
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort' }), {
      target: { value: 'published' },
    })
    expect(localStorage.getItem('spyglass:sort')).toBe('published')
    expect(scrollSpy).toHaveBeenCalledWith(0, 0)
  })

  it('search results keep their relevance order regardless of the sort toggle', async () => {
    vi.stubGlobal('scrollTo', vi.fn())
    localStorage.setItem('spyglass:sort', 'published')
    const now = Date.now()
    // FTS relevance order: best match first, even though it was published EARLIER than the
    // second hit — a published-desc sort would swap them; the toggle must not.
    const hits = [
      { ...makeCard({ id: 41, title: 'Best match', published_at: new Date(now - 5 * 86400_000).toISOString() }), snippet: 'about [memory] one' },
      { ...makeCard({ id: 42, title: 'Weaker match', published_at: new Date(now - 3600_000).toISOString() }), snippet: 'about [memory] two' },
    ]
    const base = stubFetch()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/api/search')) {
        return new Response(JSON.stringify(hits), { status: 200 })
      }
      return base(input, init)
    }))
    renderView()
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'memory' } })
    await screen.findByText('Best match')
    const titles = screen.getAllByText(/Best match|Weaker match/).map((el) => el.textContent)
    expect(titles).toEqual(['Best match', 'Weaker match'])
    localStorage.removeItem('spyglass:sort')
  })

  it('thumb (feedback) merges the full card in place immediately, then debounces onReload', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const onMerge = vi.fn()
    const onReload = vi.fn()
    renderView({ onMerge, onReload })
    // Click the thumbs-up button on the first row action cluster
    const thumbsUpButtons = screen.getAllByRole('button', { name: 'Thumbs up' })
    fireEvent.click(thumbsUpButtons[0])
    // The full card merges in place as soon as the API call resolves — no wait for a reload.
    await waitFor(() => expect(onMerge).toHaveBeenCalledWith(1, expect.objectContaining({ feedback: 'up' })))
    // onReload does not fire immediately; it is scheduled after the debounce window.
    expect(onReload).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(600)
    expect(onReload).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('coalesces a burst of thumbs into a single debounced onReload', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const onReload = vi.fn()
    renderView({ onReload })
    const thumbsUpButtons = screen.getAllByRole('button', { name: 'Thumbs up' })
    // Two rapid thumbs (well within the debounce window) must coalesce into one reload.
    fireEvent.click(thumbsUpButtons[0])
    await vi.advanceTimersByTimeAsync(100)
    fireEvent.click(thumbsUpButtons[1])
    await vi.advanceTimersByTimeAsync(600)
    expect(onReload).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('filters by category chips loaded from the service', async () => {
    renderView()
    fireEvent.click(await screen.findByRole('button', { name: 'Healthcare AI (1)' }))
    expect(screen.queryByText('First card')).not.toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()
  })

  it('uses server FTS search and shows the snippet', async () => {
    renderView()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'memory' },
    })
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
      expect(calls.some((u) => u.includes('/api/search?q=memory'))).toBe(true)
    })
    expect(await screen.findByText(/about/)).toBeInTheDocument()
    expect(screen.queryByText('First card')).not.toBeInTheDocument()
  })

  it('applies bulk relevance to every selected card, then deselects', async () => {
    const onMerge = vi.fn()
    const onReload = vi.fn()
    renderView({ onMerge, onReload })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Second card' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'H' }))
    await waitFor(() => {
      expect(onMerge).toHaveBeenCalledWith(1, { relevance: 'high', relevance_override: true })
      expect(onMerge).toHaveBeenCalledWith(2, { relevance: 'high', relevance_override: true })
    })
    // After bulk relevance, onReload should be called
    await waitFor(() => expect(onReload).toHaveBeenCalled())
    // The action consumed the selection; the bar disappears.
    expect(screen.queryByText('2 selected')).not.toBeInTheDocument()
  })

  it('archives the selection through onUpdate and clears it', async () => {
    const onUpdate = vi.fn()
    renderView({ onUpdate })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    // Multiple "Archive" buttons now exist: the SelectionBar bulk action (first in DOM)
    // and per-row actions. Click the SelectionBar one (index 0, rendered above the list).
    const [bulkArchiveBtn] = screen.getAllByRole('button', { name: 'Archive' })
    fireEvent.click(bulkArchiveBtn)
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(1, { state: 'dismissed' }))
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument()
  })

  it('seeds a compare session with the selected ids, then deselects (issue #6)', async () => {
    const onOpenClaude = vi.fn()
    renderView({ onOpenClaude })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(onOpenClaude).toHaveBeenCalledWith([1], expect.stringMatching(/compare/i))
    // Opening the session consumed the selection; the bar disappears (matches the
    // bulk-action deselect convention).
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument()
  })

  it('offers ONE Claude entry point; the session itself presents the menu, then deselects', () => {
    const onOpenClaude = vi.fn()
    renderView({ onOpenClaude })
    // The old per-action buttons are consolidated away.
    expect(screen.queryByRole('button', { name: /smart filter/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /train preferences/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /recategorize/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    fireEvent.click(screen.getByRole('button', { name: /open claude code/i }))
    // No prompt: the service's DEFAULT_PROMPT makes the session ask via a menu.
    expect(onOpenClaude).toHaveBeenCalledWith([1])
    // Opening the session deselects, same as the bulk actions (issue #6).
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument()
  })

  it('clears the search box from its inline clear button', async () => {
    renderView()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'memory' },
    })
    const clear = await screen.findByRole('button', { name: 'Clear search' })
    fireEvent.click(clear)
    expect((screen.getByRole('textbox', { name: 'Search' }) as HTMLInputElement).value).toBe('')
    expect(screen.getByText('First card')).toBeInTheDocument()
  })

  it('leaves quality actions (compare, deep dive) on the default model', () => {
    const onOpenClaude = vi.fn()
    renderView({ onOpenClaude })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    fireEvent.click(screen.getByRole('button', { name: 'Deep dive' }))
    expect(onOpenClaude).toHaveBeenCalledWith([1], expect.stringMatching(/deep dive/i))
  })

  it('keeps the reader column sticky beside the long list (wide mode)', async () => {
    renderView()
    fireEvent.click(screen.getByText('Second card'))
    await screen.findByText('Stored text.')
    const column = screen.getByTestId('reader-column')
    // Sticky + own scroll (the .reader-column CSS): clicking a row deep in the
    // list never requires scrolling back to the top to see the reader.
    expect(column.className).toContain('reader-column')
  })

  it("row's Claude action calls onOpenClaude with that card's id only", () => {
    const onOpenClaude = vi.fn()
    renderView({ onOpenClaude })
    // The first rendered "Open in Claude" button belongs to the first card (id=1).
    const claudeButtons = screen.getAllByRole('button', { name: 'Open in Claude' })
    fireEvent.click(claudeButtons[0])
    expect(onOpenClaude).toHaveBeenCalledWith([1])
  })

  it("row's delete action calls onDelete with that card's id after confirm", () => {
    const onDelete = vi.fn()
    renderView({ onDelete })
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButtons[0]) // First card's trash button.
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('prunes deleted card from FTS results so no phantom row remains', async () => {
    // Stub fetch so that a search for "memory" returns only cards[1] (id=2).
    // cards[2] ("Low card") is excluded from results to confirm the search replaced
    // the initial card list before we attempt the delete.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
        if (url.includes('/api/search')) {
          // Return only First card and Second card (not Low card).
          return respond([
            { ...cards[0], snippet: 'first snippet' },
            { ...cards[1], snippet: 'second snippet' },
          ])
        }
        if (url.includes('/api/categories')) return respond(categories)
        if (url.includes('/fulltext')) return respond({ status: 'ok', markdown: '' })
        return respond({})
      }),
    )

    const onDelete = vi.fn()
    renderView({ onDelete })

    // Trigger FTS search so results replace the default cards list.
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), {
      target: { value: 'memory' },
    })
    // Wait until "Low card" disappears — that confirms the FTS results replaced the
    // initial cards prop (results array excludes "Low card").
    await waitFor(() => expect(screen.queryByText('Low card')).not.toBeInTheDocument())
    expect(screen.getByText('First card')).toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()

    // Delete "First card" (id=1) via its row button.
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButtons[0])
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

    // The parent onDelete must have been called.
    expect(onDelete).toHaveBeenCalledWith(1)

    // The deleted card must no longer appear in the rendered list.
    await waitFor(() => expect(screen.queryByText('First card')).not.toBeInTheDocument())
    // The remaining result card must still be visible.
    expect(screen.getByText('Second card')).toBeInTheDocument()
  })

  it('removes deleted card from the selected set', async () => {
    // Proves setSelected prune: select a card then delete it; the selection bar
    // count drops to zero and the "N selected" banner disappears.
    renderView()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    expect(screen.getByText('1 selected')).toBeInTheDocument()

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButtons[0])
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

    await waitFor(() => expect(screen.queryByText('1 selected')).not.toBeInTheDocument())
  })

  // End-to-end wiring from GET /api/fetch-jobs/active to the row marker.
  // This is the path that makes an in-flight fetch visible after a dashboard reload, when
  // no component in the tree ever saw it start.
  it('marks list rows the service reports as having a fetch in flight', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/fetch-jobs/active')) {
          return new Response(JSON.stringify({ card_ids: [3] }), { status: 200 })
        }
        return stubFetch()(input, init)
      }),
    )
    renderView()
    const marker = await screen.findByLabelText('fetching full text')
    expect(marker.closest('.card-row')).toHaveTextContent('Low card')
    expect(screen.getAllByLabelText('fetching full text')).toHaveLength(1)
  })

  it('shows no pending markers when the service reports an empty queue', async () => {
    renderView()
    await waitFor(() => expect(screen.getByText('First card')).toBeInTheDocument())
    expect(screen.queryByLabelText('fetching full text')).not.toBeInTheDocument()
  })
})
