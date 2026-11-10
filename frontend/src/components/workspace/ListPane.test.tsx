// Tests for the list pane: rows, relevance dots, selection, summary display,
// and the per-item action cluster. Filtering (hide) is done upstream; ListPane
// renders every card it receives.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { makeCard } from '../../test/fixtures'
import { ListPane } from './ListPane'

// virtua needs real layout (absent in jsdom), so it renders nothing here. Render its
// children directly so the behavioral assertions see every row; real virtualization is
// verified in-browser.
vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const cards = [
  makeCard({ id: 1, title: 'High card', relevance: 'high', effective_relevance: 'high', category: 'Agentic AI', summary: 'A high-relevance summary.' }),
  makeCard({
    id: 2,
    title: 'Low card',
    relevance: 'low',
    effective_relevance: 'low',
    relevance_reason: 'introductory; below your depth threshold',
    summary: 'A low-relevance summary.',
  }),
]

const noop = () => {}

function renderPane(overrides: Partial<Parameters<typeof ListPane>[0]> = {}) {
  return render(
    <ListPane
      cards={cards}
      activeId={1}
      selected={new Set<number>()}
      onOpen={noop}
      onToggle={noop}
      onClaude={noop}
      onOpenExternal={noop}
      onArchive={noop}
      onDelete={noop}
      onSetFeedback={noop}
      {...overrides}
    />,
  )
}

describe('ListPane', () => {
  it('renders a row per card with title, source and category', () => {
    renderPane()
    expect(screen.getByText('High card')).toBeInTheDocument()
    expect(screen.getByText(/Agentic AI/)).toBeInTheDocument()
  })

  it('shows the article age on the row meta line with a full-timestamp tooltip', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 3600_000).toISOString()
    render(
      <ListPane
        cards={[makeCard({ id: 21, title: 'Dated card', published_at: threeHoursAgo })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    const age = screen.getByText(/3h ago/)
    expect(age).toBeInTheDocument()
    expect(age).toHaveAttribute('title', expect.stringContaining('published'))
  })

  it('falls back to the collected date, saying so in the tooltip, when published_at is null', () => {
    const oneDayAgo = new Date(Date.now() - 24 * 3600_000).toISOString()
    render(
      <ListPane
        cards={[makeCard({ id: 22, title: 'Undated card', published_at: null, created_at: oneDayAgo })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    const age = screen.getByText(/1d ago/)
    expect(age).toHaveAttribute('title', expect.stringContaining('collected'))
  })

  it('owns its scroll: the root is a .list-column scroll container with the forwarded ref', () => {
    // The list must NOT ride the window scroll (virtua window math breaks under the
    // app's CSS zoom); it owns an element scroll container the caller can reset.
    const scrollRef = { current: null as HTMLDivElement | null }
    renderPane({ scrollRef })
    const pane = screen.getByTestId('list-pane')
    expect(pane.className).toContain('list-column')
    expect(scrollRef.current).toBe(pane)
  })

  it('shows the real origin (feed/site) instead of just the collector', () => {
    render(
      <ListPane
        cards={[makeCard({ id: 9, title: 'Origin card', origin: 'NVIDIA Technical Blog' })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    expect(screen.getByText('NVIDIA TECHNICAL BLOG')).toBeInTheDocument()
  })

  it('shows a relevance dot labelled with the effective_relevance level', () => {
    renderPane()
    // Dot title reflects effective_relevance (not raw relevance)
    expect(screen.getByTitle('relevance: high')).toBeInTheDocument()
  })

  it('shows a dot labelled "unjudged" when effective_relevance is null', () => {
    render(
      <ListPane
        cards={[makeCard({ id: 10, title: 'Unjudged card', effective_relevance: null })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    expect(screen.getByTitle('relevance: unjudged')).toBeInTheDocument()
  })

  it('renders all cards passed in without dimming or hiding any', () => {
    // Filtering is done upstream; ListPane renders whatever it receives
    renderPane()
    expect(screen.getByText('High card')).toBeInTheDocument()
    expect(screen.getByText('Low card')).toBeInTheDocument()
    // No opacity-45 class (no dimming)
    const rows = document.querySelectorAll('.card-row')
    rows.forEach((row) => expect(row.className).not.toContain('opacity-45'))
  })

  it('opens a row on click', () => {
    const onOpen = vi.fn()
    renderPane({ onOpen })
    fireEvent.click(screen.getByText('Low card'))
    expect(onOpen).toHaveBeenCalledWith(2)
  })

  it('toggles selection via the checkbox without opening the row', () => {
    const onOpen = vi.fn()
    const onToggle = vi.fn()
    renderPane({ onOpen, onToggle })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select High card' }))
    expect(onToggle).toHaveBeenCalledWith(1, true)
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('marks rows the user has overridden with "you set"', () => {
    render(
      <ListPane
        cards={[makeCard({ id: 3, title: 'Tweaked', relevance: 'high', relevance_override: true })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    expect(screen.getByText('you set')).toBeInTheDocument()
  })

  it('shows the card summary text below the meta', () => {
    renderPane()
    expect(screen.getByText('A high-relevance summary.')).toBeInTheDocument()
    expect(screen.getByText('A low-relevance summary.')).toBeInTheDocument()
  })

  it('renders an action cluster with all four buttons in each row', () => {
    renderPane()
    // One button per row × 2 rows.
    expect(screen.getAllByRole('button', { name: 'Open in Claude' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Open in browser' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Archive' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(2)
  })

  it('clicking a row action does not trigger onOpen (stopPropagation)', () => {
    const onOpen = vi.fn()
    const onArchive = vi.fn()
    renderPane({ onOpen, onArchive })
    // Click the Archive button on the first row.
    fireEvent.click(screen.getAllByRole('button', { name: 'Archive' })[0])
    expect(onArchive).toHaveBeenCalledWith(1)
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('wraps each row\'s actions in an absolutely-positioned drawer (no reserved text width)', () => {
    renderPane()
    const drawers = screen.getAllByTestId('row-action-drawer')
    expect(drawers).toHaveLength(2)
    // Absolute positioning lifts the toolbar out of the row's flex flow, so the
    // title/summary column keeps full width whether or not the row is hovered.
    drawers.forEach((drawer) => expect(drawer.className).toContain('absolute'))
  })

  it('renders a disclosure handle on each row', () => {
    renderPane()
    expect(screen.getAllByTestId('row-action-handle')).toHaveLength(2)
  })

  // Rated cards need an at-rest signal since the thumbs themselves live in a
  // hover-only drawer -- a persistent marker in the meta line shows past ratings at a glance.
  it('shows a persistent liked marker in the meta line when feedback is "up"', () => {
    render(
      <ListPane
        cards={[makeCard({ id: 30, title: 'Liked card', feedback: 'up' })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    expect(screen.getByLabelText('you liked this')).toBeInTheDocument()
  })

  it('shows a persistent disliked marker in the meta line when feedback is "down"', () => {
    render(
      <ListPane
        cards={[makeCard({ id: 31, title: 'Disliked card', feedback: 'down' })]}
        activeId={null}
        selected={new Set<number>()}
        onOpen={noop}
        onToggle={noop}
        onClaude={noop}
        onOpenExternal={noop}
        onArchive={noop}
        onDelete={noop}
        onSetFeedback={noop}
      />,
    )
    expect(screen.getByLabelText('you disliked this')).toBeInTheDocument()
  })

  it('shows no feedback marker when feedback is null', () => {
    renderPane() // both fixture cards default to feedback: null
    expect(screen.queryByLabelText('you liked this')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('you disliked this')).not.toBeInTheDocument()
  })

  // The pending marker is what makes a queued fetch visible away from the
  // reader that started it.
  it('marks only the rows with a fetch in flight', () => {
    renderPane({ fetchingIds: new Set([2]) })
    const markers = screen.getAllByLabelText('fetching full text')
    expect(markers).toHaveLength(1)
    // The marker belongs to the row whose job is active, not merely to some row.
    expect(markers[0].closest('.card-row')).toHaveTextContent('Low card')
  })

  it('shows no pending marker when nothing is in flight', () => {
    renderPane({ fetchingIds: new Set<number>() })
    expect(screen.queryByLabelText('fetching full text')).not.toBeInTheDocument()
  })

  it('renders without a pending marker when the caller passes no fetch state at all', () => {
    renderPane()
    expect(screen.queryByLabelText('fetching full text')).not.toBeInTheDocument()
  })

})
