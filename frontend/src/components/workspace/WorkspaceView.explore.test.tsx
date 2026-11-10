// WorkspaceView explore mode + Research action: scored neighbourhood
// list with banner, filter-preserving exit, chaining, and the research prompt.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'
import type { ScoredCard } from '../../lib/types'
import { WorkspaceView } from './WorkspaceView'

// virtua needs real layout (absent in jsdom); render its children directly.
vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const cards = [
  makeCard({ id: 1, title: 'First card', relevance: 'high', effective_relevance: 'high' }),
  makeCard({ id: 2, title: 'Second card', relevance: 'medium', effective_relevance: 'medium' }),
  makeCard({ id: 3, title: 'Low card', relevance: 'low', effective_relevance: 'low' }),
]

const neighbours: ScoredCard[] = [
  { ...makeCard({ id: 5, title: 'Neighbour A' }), score: 0.81 },
  { ...makeCard({ id: 6, title: 'Neighbour B' }), score: 0.52 },
]

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
    if (url.includes('/fulltext')) return respond({ status: 'ok', markdown: 'Stored text.' })
    if (url.includes('/api/categories')) return respond([])
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

/** Enter explore mode from the first card's row action. */
async function enterExplore() {
  fireEvent.click(screen.getAllByRole('button', { name: 'Explore similar' })[0])
  await screen.findByText(/similar to: first card/i)
}

describe('WorkspaceView explore mode', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue(neighbours)
    vi.stubGlobal('fetch', stubFetch())
    vi.stubGlobal('scrollTo', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('enters explore from a row action: banner + scored neighbour rows replace the list', async () => {
    renderView()
    await enterExplore()
    expect(api.getSimilar).toHaveBeenCalledWith(1, 20)
    expect(await screen.findByText('Neighbour A')).toBeInTheDocument()
    expect(screen.getByText('Neighbour B')).toBeInTheDocument()
    // The normal list rows are replaced by the neighbourhood.
    expect(screen.queryByText('Second card')).not.toBeInTheDocument()
    // Scores show subtly on the rows.
    expect(screen.getByText('0.81')).toBeInTheDocument()
    expect(screen.getByText('0.52')).toBeInTheDocument()
  })

  it('the close button exits and restores the list without clobbering filters', async () => {
    renderView()
    // Hide everything below medium first: Low card leaves the list.
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }))
    fireEvent.change(screen.getByRole('combobox', { name: /relevance filter/i }), {
      target: { value: 'medium' },
    })
    expect(screen.queryByText('Low card')).not.toBeInTheDocument()
    await enterExplore()
    fireEvent.click(screen.getByRole('button', { name: 'Exit explore' }))
    // Normal list is back with the filter still applied.
    expect(screen.getByText('First card')).toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()
    expect(screen.queryByText('Low card')).not.toBeInTheDocument()
    expect(screen.queryByText(/similar to:/i)).not.toBeInTheDocument()
  })

  it('Escape exits explore mode', async () => {
    renderView()
    await enterExplore()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText(/similar to:/i)).not.toBeInTheDocument()
    expect(screen.getByText('Second card')).toBeInTheDocument()
  })

  it('a neighbour row explore action re-seeds the neighbourhood (chaining)', async () => {
    renderView()
    await enterExplore()
    await screen.findByText('Neighbour A')
    fireEvent.click(screen.getAllByRole('button', { name: 'Explore similar' })[0])
    expect(await screen.findByText(/similar to: neighbour a/i)).toBeInTheDocument()
    expect(api.getSimilar).toHaveBeenCalledWith(5, 20)
  })

  it('clicking a neighbour row opens it in the reader as usual', async () => {
    renderView()
    await enterExplore()
    fireEvent.click(await screen.findByText('Neighbour A'))
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
  })

  it('shows the empty message when there are no neighbours yet', async () => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
    renderView()
    await enterExplore()
    expect(
      await screen.findByText(/no similar articles yet — embeddings may still be building/i),
    ).toBeInTheDocument()
  })

  it('shows a loading state while the neighbourhood fetch is in flight', async () => {
    vi.spyOn(api, 'getSimilar').mockReturnValue(new Promise(() => {}))
    renderView()
    await enterExplore()
    expect(screen.getByText(/finding similar articles/i)).toBeInTheDocument()
  })

  it('the reader toolbar Explore action enters explore for the open card', async () => {
    renderView()
    fireEvent.click(screen.getByText('Second card'))
    await screen.findByText('Stored text.')
    // The toolbar's explore button is the last one rendered (rows come first in the DOM).
    const buttons = screen.getAllByRole('button', { name: 'Explore similar' })
    fireEvent.click(buttons[buttons.length - 1])
    expect(await screen.findByText(/similar to: second card/i)).toBeInTheDocument()
    expect(api.getSimilar).toHaveBeenCalledWith(2, 20)
  })

  it('the reader toolbar Research action seeds Claude with the research prompt', async () => {
    const onOpenClaude = vi.fn()
    renderView({ onOpenClaude })
    fireEvent.click(screen.getByText('Second card'))
    await screen.findByText('Stored text.')
    fireEvent.click(screen.getByRole('button', { name: 'Research on the web' }))
    expect(onOpenClaude).toHaveBeenCalledWith(
      [2],
      'Use the spyglass skill: research NEW articles similar to card 2 ("Second card"). ' +
        'Search the web for closely related articles/papers, evaluate each against my ' +
        'interest profile, and file the best finds into Spyglass via POST /api/pages ' +
        '{"url": ...} so they are enriched and judged.',
    )
  })
})
