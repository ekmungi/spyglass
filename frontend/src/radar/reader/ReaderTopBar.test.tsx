// Tests for the reader's top bar additions: the Follow button, and the More menu's width steps.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getAppearance, initAppearance, setAppearance } from '../appearance/appearanceStore'
import type { ItemDetail } from '../api/types'
import { closeClaudeDialog, getClaudeDialog } from '../claude/claudeStore'
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
  published_at: null,
  state: { saved: false, opened: true, vote: null, from_user: false, captured_via: null, vault_path: null },
  story_sources: [],
  reader: null,
} as unknown as ItemDetail

function renderBar() {
  return render(<ReaderTopBar detail={detail} showPdf={false} onTogglePdf={() => undefined} />)
}

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
  initAppearance()
  vi.clearAllMocks()
  api.suggestTracksForItem.mockReturnValue(new Promise(() => undefined))
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

  it('shows the PDF label in the bar, never "min read" for a long thesis', () => {
    const pdf = { ...detail, reader: { ...base, kind: 'pdf', word_count: 90000, page_count: 212 } } as unknown as ItemDetail
    render(<ReaderTopBar detail={pdf} showPdf={false} onTogglePdf={() => undefined} />)
    expect(screen.getByText(/PDF · 212 pages/)).toBeInTheDocument()
    expect(screen.queryByText(/min read/)).not.toBeInTheDocument()
  })
})

describe('ReaderTopBar', () => {
  it('opens "Follow more like this" for this item from the Follow button', async () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Follow' }))
    expect(screen.getByRole('dialog', { name: 'Follow more like this' })).toBeInTheDocument()
    await waitFor(() => expect(api.suggestTracksForItem).toHaveBeenCalledWith(42, expect.anything()))
  })

  it('steps the text width narrower and wider from the More menu, and disables a step at the limit', () => {
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Wider text' }))
    expect(getAppearance().textWidth).toBe(720)
    expect(document.documentElement.style.getPropertyValue('--measure')).toBe('720px')
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Narrower text' }))
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Narrower text' }))
    expect(getAppearance().textWidth).toBe(640)
  })

  it('has "Open in Claude Code…" in the More menu, which opens the dialog for this item', () => {
    renderBar()
    expect(getClaudeDialog()).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Open in Claude Code…' }))
    expect(getClaudeDialog()).toMatchObject({ itemId: 42 })
    closeClaudeDialog()
  })

  it('has "Show related in the Feed" in the More menu, which opens the Feed on the neighbours of this item', () => {
    window.history.replaceState(null, '', '/#/item/42')
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Show related in the Feed' }))
    expect(window.location.hash).toBe('#/feed?related_item=42')
  })

  it('offers no further step at the narrowest width', () => {
    setAppearance({ textWidth: 560 })
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    expect(screen.getByRole('menuitem', { name: 'Narrower text' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('menuitem', { name: 'Wider text' })).not.toHaveAttribute('aria-disabled')
  })
})
