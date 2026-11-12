// Tests for the reader's untrusted-address handling: the player iframe is sandboxed and limited
// to known players, and "Open original" never opens or links an unsafe address.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemDetail } from '../api/types'
import { ReaderBody } from './ReaderBody'
import { ReaderTopBar } from './ReaderTopBar'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function detail(overrides: Partial<ItemDetail> & { readerKind?: 'video' | 'article'; status?: 'ok' | 'failed'; altUrl?: string | null }): ItemDetail {
  const { readerKind = 'video', status = 'ok', altUrl = null, ...rest } = overrides
  return {
    id: 9,
    title: 'A talk',
    headline: 'A talk',
    url: 'https://www.youtube.com/watch?v=abc123',
    source: 'rss',
    origin: 'Example',
    published_at: null,
    fetched_at: '2026-11-12T08:00:00',
    kind: 'video',
    section: '',
    section_label: '',
    tier: 'notable',
    score: null,
    why: null,
    key_points: [],
    entities: [],
    signal: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    has_reader: true,
    summary: null,
    reader: { kind: readerKind, html: '<p>Notes</p>', title: null, byline: null, site: null, lead_image: null, word_count: 10, source_url: null, alt_url: altUrl, status, error: null },
    related: [],
    story_sources: [],
    threads: [],
    ...rest,
  }
}

const noop = () => undefined

describe('ReaderBody player', () => {
  it('sandboxes a known player and sends the origin as referrer, which YouTube needs to play', () => {
    const { container } = render(<ReaderBody detail={detail({})} showPdf={false} proseRef={null} onRefreshed={noop} />)
    const frame = container.querySelector('.r-video iframe') as HTMLIFrameElement
    expect(frame.getAttribute('src')).toBe('https://www.youtube-nocookie.com/embed/abc123')
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-presentation')
    expect(frame.getAttribute('referrerpolicy')).toBe('strict-origin-when-cross-origin')
  })

  it('renders no player for an address outside the player list', () => {
    const { container } = render(<ReaderBody detail={detail({ url: 'https://evil.example/watch' })} showPdf={false} proseRef={null} onRefreshed={noop} />)
    expect(container.querySelector('iframe')).toBeNull()
    expect(screen.getByText('Notes')).toBeInTheDocument()
  })

  it('renders no player for an inline page outside sample mode', () => {
    const { container } = render(<ReaderBody detail={detail({ url: 'data:text/html,<script>alert(1)</script>' })} showPdf={false} proseRef={null} onRefreshed={noop} />)
    expect(container.querySelector('iframe')).toBeNull()
  })
})

describe('Open original', () => {
  it('opens a web address in the failed-copy state', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    render(<ReaderBody detail={detail({ readerKind: 'article', status: 'failed', url: 'https://example.org/a' })} showPdf={false} proseRef={null} onRefreshed={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /Open original/ }))
    expect(open).toHaveBeenCalledWith('https://example.org/a', '_blank', 'noopener,noreferrer')
  })

  it('shows an unsafe address as text with no button', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    render(<ReaderBody detail={detail({ readerKind: 'article', status: 'failed', url: 'javascript:alert(1)' })} showPdf={false} proseRef={null} onRefreshed={noop} />)
    expect(screen.queryByRole('button', { name: /Open original/ })).toBeNull()
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
  })

  it('has no Open original action in the top bar for an unsafe address', () => {
    render(<ReaderTopBar detail={detail({ url: 'javascript:alert(1)' })} showPdf={false} onTogglePdf={noop} />)
    expect(screen.queryByRole('button', { name: /Open original/ })).toBeNull()
  })

  it('opens a web address from the top bar', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    render(<ReaderTopBar detail={detail({ url: 'https://example.org/a' })} showPdf={false} onTogglePdf={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /Open original/ }))
    expect(open).toHaveBeenCalledWith('https://example.org/a', '_blank', 'noopener,noreferrer')
  })
})

describe('ReaderBody failure', () => {
  it('explains a failed read in one plain sentence and keeps the technical text under Details', () => {
    const failed = detail({ readerKind: 'article', status: 'failed' })
    const withError = { ...failed, reader: { ...(failed.reader as NonNullable<ItemDetail['reader']>), error: 'failed at T0 (HTTP 401): HTTP 401' } }
    const { container } = render(<ReaderBody detail={withError} showPdf={false} proseRef={null} onRefreshed={noop} />)
    expect(screen.getByText('The site asked for a sign-in.')).toBeInTheDocument()
    const details = container.querySelector('details') as HTMLDetailsElement
    expect(details.textContent).toContain('failed at T0 (HTTP 401)')
    expect(screen.queryByText('failed at T0 (HTTP 401): HTTP 401', { ignore: 'details *' })).not.toBeInTheDocument()
  })
})

