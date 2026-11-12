// Tests for the reader's "bring it in from your browser" hint on a failed copy or a preview.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ItemDetail, ReaderDoc } from '../api/types'
import { ReaderBody } from '../reader/ReaderBody'

const router = vi.hoisted(() => ({ navigate: vi.fn() }))
vi.mock('../router', async (original) => ({ ...(await original<typeof import('../router')>()), ...router }))

const HINT = 'You can read it in your browser and bring it in: open the original, then use your Send to Spyglass button.'

function detail(reader: Partial<ReaderDoc> | null, url = 'https://news.example.com/story'): ItemDetail {
  return {
    id: 9, title: 'A story', headline: 'A story', url, source: 'rss', origin: 'News', published_at: null,
    fetched_at: '2026-11-12T08:00:00', kind: 'news', section: '', section_label: '', tier: 'notable', score: null,
    why: null, key_points: [], entities: [], signal: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    has_reader: true, summary: null, related: [], story_sources: [], threads: [],
    reader: reader && {
      kind: 'article', html: '<p>The first paragraph.</p>', title: null, byline: null, site: null, lead_image: null,
      word_count: 3, source_url: null, alt_url: null, status: 'ok', error: null, ...reader,
    },
  }
}

const show = (value: ItemDetail) => render(<ReaderBody detail={value} showPdf={false} proseRef={{ current: null }} onRefreshed={() => undefined} />)

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.restoreAllMocks())

describe('the bring-in hint in the reader', () => {
  it('appears under the reason of a failed copy, with the setup link', () => {
    show(detail({ status: 'failed', html: '', error: 'failed at T0 (HTTP 403): HTTP 403' }))
    expect(screen.getByText('The site asked for a sign-in.')).toBeInTheDocument()
    expect(screen.getByText(HINT)).toBeInTheDocument()
    // The failed state already has one Open original button; the hint does not add a second.
    expect(screen.getAllByRole('button', { name: 'Open original' })).toHaveLength(1)
    const setup = screen.getByRole('link', { name: 'How to set this up' })
    expect(setup).toHaveAttribute('href', '#/settings?section=bring-in')
    fireEvent.click(setup)
    expect(router.navigate).toHaveBeenCalledWith({ name: 'settings', section: 'bring-in' })
  })

  it('shows a preview notice above the article, then the hint with Open original', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { container } = show(detail({ partial: true, notice: 'Only a preview is available; the site limits this article to subscribers.' }))
    const notice = screen.getByText('Only a preview is available; the site limits this article to subscribers.')
    const paragraph = screen.getByText('The first paragraph.')
    expect(notice.compareDocumentPosition(paragraph) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText(HINT)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open original' }))
    expect(open).toHaveBeenCalledWith('https://news.example.com/story', '_blank', 'noopener,noreferrer')
    expect(container.querySelector('.rim-notice')).not.toBeNull()
  })

  it('uses the standard sentence when a preview carries no notice', () => {
    show(detail({ partial: true, notice: null }))
    expect(screen.getByText('Only a preview is available; the site limits this article to subscribers.')).toBeInTheDocument()
  })

  it('stays away from a complete document', () => {
    show(detail({}))
    expect(screen.queryByText(HINT)).toBeNull()
  })

  it('never offers to open an address that is not a plain web address', () => {
    show(detail({ partial: true }, 'javascript:alert(1)'))
    expect(screen.queryByRole('button', { name: 'Open original' })).toBeNull()
    expect(screen.getByText(HINT)).toBeInTheDocument()
  })
})
