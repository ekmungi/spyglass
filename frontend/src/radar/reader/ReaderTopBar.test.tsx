// Tests for the reader's top bar: previous and next story with the count, the thumbs, the icon
// buttons (copy the link, narrower and wider text, other sources, the chat icon), the paper's
// PDF/Text switch, and the short More menu. The reading label itself is tested here too.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getAppearance, initAppearance, setAppearance } from '../appearance/appearanceStore'
import type { ItemDetail } from '../api/types'
import { getAssistState, setAssistOpen } from '../assistant/assistStore'
import { closeClaudeDialog, getClaudeDialog } from '../claude/claudeStore'
import { navigate, useRoute } from '../router'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { resetReadingList, setReadingList } from '../state/readingList'
import { readingLabel } from './readingLabel'
import { ReaderTopBar } from './ReaderTopBar'

const api = vi.hoisted(() => ({ suggestTracksForItem: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const detail = {
  id: 42,
  title: 'A title',
  headline: 'A headline',
  url: 'https://example.org/a',
  origin: 'Example Wire',
  published_at: '2026-11-12T08:00:00Z',
  state: { saved: false, opened: true, vote: null, from_user: false, captured_via: null, vault_path: null },
  story_sources: [],
  reader: { kind: 'article', status: 'ok', site: 'Example Site', word_count: 2300 },
  filing: null,
  filed: null,
} as unknown as ItemDetail

// Twenty-seven stories; the reader has the second one open.
const IDS = Array.from({ length: 27 }, (_, index) => 100 + index)

const noop = () => undefined

function renderBar(item: ItemDetail = detail) {
  return render(<ReaderTopBar detail={item} showPdf={false} onTogglePdf={noop} />)
}

/** The text of the tooltip bubble that belongs to a control. */
function tipOf(element: HTMLElement): string | null | undefined {
  return element.closest('.r-tip')?.querySelector('.r-tip__bubble')?.textContent
}

/** The names of the More menu's entries, in order. */
function moreEntries(): string[] {
  fireEvent.click(screen.getByRole('button', { name: 'More' }))
  return screen.getAllByRole('menuitem').map((entry) => entry.textContent ?? '')
}

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
  initAppearance()
  vi.clearAllMocks()
  api.suggestTracksForItem.mockReturnValue(new Promise(() => undefined))
  resetReadingList()
  // Filing is set up, so the File in vault control is in the bar (and no request is made for it).
  setFilingConfigured(true)
  setAssistOpen('reader', false)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  resetFilingConfigured()
})

describe('reading label', () => {
  const base = { kind: 'article', word_count: 2300, page_count: null } as unknown as NonNullable<ItemDetail['reader']>

  it('says minutes for an article', () => {
    expect(readingLabel(base)).toBe('10 min read')
    expect(readingLabel({ ...base, word_count: 0 })).toBeNull()
  })

  it('says "under a minute" for a very short text, never "0 min read"', () => {
    expect(readingLabel({ ...base, word_count: 60 })).toBe('under a minute')
    expect(readingLabel({ ...base, word_count: 150 })).toBe('1 min read')
  })

  it('says "PDF · N pages" for a PDF with a known page count, and nothing when the count is unknown', () => {
    expect(readingLabel({ ...base, kind: 'pdf', word_count: 90000, page_count: 212 })).toBe('PDF · 212 pages')
    expect(readingLabel({ ...base, kind: 'pdf', word_count: 90000, page_count: 1 })).toBe('PDF · 1 page')
    expect(readingLabel({ ...base, kind: 'pdf', word_count: 90000, page_count: null })).toBeNull()
    expect(readingLabel({ ...base, kind: 'pdf', word_count: 230, page_count: undefined })).toBeNull()
  })
})

describe('previous and next story', () => {
  it('shows Previous story, Next story and "2 of 27 in Today", and Next replaces the entry with the third story', () => {
    window.history.replaceState(null, '', `/#/item/${IDS[1]}`)
    setReadingList('Today', IDS)
    renderBar({ ...detail, id: IDS[1] })
    expect(screen.getByRole('button', { name: 'Previous story' })).toBeInTheDocument()
    expect(screen.getByText('2 of 27 in Today')).toBeInTheDocument()
    const entries = window.history.length
    fireEvent.click(screen.getByRole('button', { name: 'Next story' }))
    expect(window.location.hash).toBe(`#/item/${IDS[2]}`)
    // A replacing navigation: no new history entry.
    expect(window.history.length).toBe(entries)
  })

  it('names the Feed by its label, and Previous goes to the first story', () => {
    window.history.replaceState(null, '', `/#/item/${IDS[1]}`)
    setReadingList('the Feed', IDS)
    renderBar({ ...detail, id: IDS[1] })
    expect(screen.getByText('2 of 27 in the Feed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous story' }))
    expect(window.location.hash).toBe(`#/item/${IDS[0]}`)
  })

  it('shows the key in each tooltip and disables a step past either end of the list', () => {
    setReadingList('Today', IDS)
    renderBar({ ...detail, id: IDS[0] })
    expect(tipOf(screen.getByRole('button', { name: 'Previous story' }))).toBe('Previous story (K)')
    expect(tipOf(screen.getByRole('button', { name: 'Next story' }))).toBe('Next story (J)')
    expect(screen.getByRole('button', { name: 'Previous story' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next story' })).toBeEnabled()
  })

  it('shows none of the three controls without a reading list, or when the item is not in it', () => {
    renderBar()
    expect(screen.queryByRole('button', { name: 'Previous story' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Next story' })).not.toBeInTheDocument()
    expect(screen.queryByText(/ of \d+ in /)).not.toBeInTheDocument()
    cleanup()
    setReadingList('Today', IDS)
    renderBar()
    expect(screen.queryByRole('button', { name: 'Next story' })).not.toBeInTheDocument()
  })

  it('keeps where the reader was opened from: after three moves, Back leaves the reader in one step', async () => {
    // A stand-in for the app: the reader for the item in the address, the list page otherwise.
    function Harness() {
      const route = useRoute()
      return route.name === 'item' ? <ReaderTopBar detail={{ ...detail, id: route.id }} showPdf={false} onTogglePdf={noop} /> : <p>The list</p>
    }
    window.history.replaceState(null, '', '/#/today')
    setReadingList('Today', IDS)
    render(<Harness />)
    act(() => navigate({ name: 'item', id: IDS[1] }))
    fireEvent.click(screen.getByRole('button', { name: 'Next story' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next story' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next story' }))
    expect(window.location.hash).toBe(`#/item/${IDS[4]}`)
    expect(screen.getByText('5 of 27 in Today')).toBeInTheDocument()
    const popped = new Promise((resolve) => window.addEventListener('popstate', resolve, { once: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await popped
    await waitFor(() => expect(window.location.hash).toBe('#/today'))
    expect(await screen.findByText('The list')).toBeInTheDocument()
  })
})

describe('the icon bar', () => {
  it('shows the thumbs at all times, with their tooltips below', () => {
    renderBar()
    const more = screen.getByRole('button', { name: 'More like this' })
    expect(more.closest('.r-votes')).toHaveClass('r-votes--always')
    expect(more.closest('.r-tip')).toHaveClass('r-tip--bottom')
    expect(screen.getByRole('button', { name: 'Less like this' }).closest('.r-tip')).toHaveClass('r-tip--bottom')
  })

  it('opens every tooltip in the bar downwards', () => {
    // The bar sits at the top of the window, so a tooltip above a button would be cut off.
    setReadingList('Today', IDS)
    const { container } = renderBar({
      ...detail,
      id: IDS[1],
      story_sources: [
        { item_id: IDS[1], name: 'Example Wire' },
        { item_id: 7, name: 'Other Wire' },
      ],
    } as unknown as ItemDetail)
    const tips = Array.from(container.querySelectorAll('.r-tip'))
    expect(tips.length).toBeGreaterThan(10)
    for (const tip of tips) expect(tip).toHaveClass('r-tip--bottom')
  })

  it('has File in vault as an icon button that keeps its menu', () => {
    renderBar()
    expect(screen.getByRole('button', { name: 'File in vault' })).toHaveClass('r-iconbtn')
    fireEvent.click(screen.getByRole('button', { name: 'More ways to file' }))
    expect(screen.getByRole('menuitem', { name: 'File as…' })).toBeInTheDocument()
  })

  it('copies the address and says "Link copied" in the tooltip until two seconds have passed', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderBar()
    expect(tipOf(screen.getByRole('button', { name: 'Copy the link' }))).toBe('Copy the link')
    fireEvent.click(screen.getByRole('button', { name: 'Copy the link' }))
    await act(async () => undefined)
    expect(writeText).toHaveBeenCalledWith('https://example.org/a')
    expect(tipOf(screen.getByRole('button', { name: 'Link copied' }))).toBe('Link copied')
    act(() => vi.advanceTimersByTime(1999))
    expect(tipOf(screen.getByRole('button', { name: 'Link copied' }))).toBe('Link copied')
    act(() => vi.advanceTimersByTime(1))
    expect(tipOf(screen.getByRole('button', { name: 'Copy the link' }))).toBe('Copy the link')
  })

  it('opens the original page from its icon button', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Open the original page' }))
    expect(open).toHaveBeenCalledWith('https://example.org/a', '_blank', 'noopener,noreferrer')
  })

  it('steps the text width with the Narrower text and Wider text buttons, and disables a step at the limit', () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Wider text' }))
    expect(getAppearance().textWidth).toBe(720)
    expect(document.documentElement.style.getPropertyValue('--measure')).toBe('720px')
    fireEvent.click(screen.getByRole('button', { name: 'Narrower text' }))
    fireEvent.click(screen.getByRole('button', { name: 'Narrower text' }))
    expect(getAppearance().textWidth).toBe(640)
    act(() => setAppearance({ textWidth: 560 }))
    expect(screen.getByRole('button', { name: 'Narrower text' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Wider text' })).toBeEnabled()
  })

  it('offers the other sources from an icon button only when there are other sources', () => {
    window.history.replaceState(null, '', '/#/item/42')
    renderBar()
    expect(screen.queryByRole('button', { name: /sources for this story/ })).not.toBeInTheDocument()
    cleanup()
    renderBar({
      ...detail,
      story_sources: [
        { item_id: 42, name: 'Example Wire' },
        { item_id: 43, name: 'Other Wire' },
        { item_id: 44, name: 'Third Wire' },
      ],
    } as unknown as ItemDetail)
    fireEvent.click(screen.getByRole('button', { name: '3 sources for this story' }))
    expect(screen.getAllByRole('menuitem')).toHaveLength(3)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Other Wire' }))
    expect(window.location.hash).toBe('#/item/43')
  })

  it('shows the chat icon only while the assistant is closed, and opens the assistant from it', () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Ask the assistant about this story' }))
    expect(getAssistState().open.reader).toBe(true)
    expect(screen.queryByRole('button', { name: 'Ask the assistant about this story' })).not.toBeInTheDocument()
  })

  it('keeps the PDF and Text switch for a paper', () => {
    const paper = { ...detail, reader: { kind: 'paper', status: 'ok' } } as unknown as ItemDetail
    const toggle = vi.fn()
    const { rerender } = render(<ReaderTopBar detail={paper} showPdf={false} onTogglePdf={toggle} />)
    fireEvent.click(screen.getByRole('button', { name: 'PDF' }))
    expect(toggle).toHaveBeenCalledTimes(1)
    rerender(<ReaderTopBar detail={paper} showPdf onTogglePdf={toggle} />)
    expect(screen.getByRole('button', { name: 'Text' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('no longer carries the source, the date or the reading time', () => {
    const { container } = renderBar()
    expect(container.textContent).not.toMatch(/Example Site|Example Wire|12 Nov 2026|min read/)
  })
})

describe('the More menu', () => {
  it('holds exactly Open in Claude Code…, Follow topics from this article and Show related in the Feed', () => {
    renderBar()
    expect(moreEntries()).toEqual(['Open in Claude Code…', 'Follow topics from this article', 'Show related in the Feed'])
  })

  it('opens the Claude Code dialog for this item', () => {
    renderBar()
    expect(getClaudeDialog()).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Open in Claude Code…' }))
    expect(getClaudeDialog()).toMatchObject({ itemId: 42 })
    closeClaudeDialog()
  })

  it('opens "Follow more like this" for this item from Follow topics from this article', async () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Follow topics from this article' }))
    expect(screen.getByRole('dialog', { name: 'Follow more like this' })).toBeInTheDocument()
    await waitFor(() => expect(api.suggestTracksForItem).toHaveBeenCalledWith(42, expect.anything()))
  })

  it('opens the Feed on the neighbours of this item from Show related in the Feed', () => {
    window.history.replaceState(null, '', '/#/item/42')
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Show related in the Feed' }))
    expect(window.location.hash).toBe('#/feed?related_item=42')
  })
})
