// Tests for the import window: which messages it takes, how it shows where a page came from, and
// the add / discard / token flows.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RadarItem, StagedImport } from '../api/types'
import { clearResourceCache } from '../hooks/useResource'
import { ACK_MESSAGE, PAGE_MESSAGE } from './bookmarklet'
import { ARM_AFTER_MS, ImportPage, SLOW_AFTER_MS } from './ImportPage'
import { REPLACE_REFUSED_MESSAGE, isAnswerableOrigin, readPageMessage, senderMismatchLine, stageErrorMessage, MAX_HTML_CHARS } from './messages'

const api = vi.hoisted(() => ({
  stageImport: vi.fn(),
  getStagedImport: vi.fn(),
  acceptStagedImport: vi.fn(),
  discardStagedImport: vi.fn(),
}))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))
const router = vi.hoisted(() => ({ navigate: vi.fn() }))
vi.mock('../router', async (original) => ({ ...(await original<typeof import('../router')>()), ...router }))

const TOKEN = 'ab'.repeat(16)
const SENDER = 'https://news.example.com'
const KEY = 'c0'.repeat(16)
const PAGE = { type: PAGE_MESSAGE, url: 'https://news.example.com/story', title: 'A story', html: '<p>Hello</p>', key: KEY }

const preview = (overrides: Partial<StagedImport> = {}): StagedImport => ({
  token: TOKEN,
  url: 'https://news.example.com/2026/11/story?id=7',
  host: 'news.example.com',
  title: 'Trial results are in',
  site: 'News Example',
  word_count: 1240,
  excerpt: 'Sentence 0 explains the new results.',
  sender: 'news.example.com',
  sender_matches: true,
  existing_item_id: null,
  replaces_existing: false,
  replace_refused: false,
  ...overrides,
})

let opener: Window
let frame: HTMLIFrameElement

/** Deliver a message to the import window as if `source` had posted it from `origin`. */
function deliver(data: unknown, origin = SENDER, source: Window | null = opener) {
  act(() => {
    window.dispatchEvent(new MessageEvent('message', { data, origin, source }))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  clearResourceCache()
  frame = document.createElement('iframe')
  document.body.appendChild(frame)
  opener = frame.contentWindow as Window
  vi.spyOn(opener, 'postMessage').mockImplementation(() => undefined)
  Object.defineProperty(window, 'opener', { value: opener, configurable: true, writable: true })
  api.stageImport.mockResolvedValue({ token: TOKEN })
  api.getStagedImport.mockResolvedValue(preview())
  api.acceptStagedImport.mockResolvedValue({ id: 42 } as RadarItem)
  api.discardStagedImport.mockResolvedValue(null)
})

afterEach(() => {
  Object.defineProperty(window, 'opener', { value: null, configurable: true, writable: true })
  frame.remove()
  vi.useRealTimers()
})

describe('readPageMessage', () => {
  it('takes only the exact shape and sizes', () => {
    expect(readPageMessage(PAGE)).toEqual({ url: PAGE.url, title: 'A story', html: '<p>Hello</p>', key: KEY })
    expect(readPageMessage({ ...PAGE, title: undefined })).toEqual({ url: PAGE.url, title: '', html: '<p>Hello</p>', key: KEY })
    // A button made before the key existed sends none; the service refuses it with a clear message.
    expect(readPageMessage({ ...PAGE, key: undefined })).toEqual({ url: PAGE.url, title: 'A story', html: '<p>Hello</p>', key: '' })
    for (const bad of [null, 'text', [PAGE], { ...PAGE, type: 'other' }, { ...PAGE, url: 7 }, { ...PAGE, url: '' }, { ...PAGE, url: 'x'.repeat(2049) },
      { ...PAGE, title: { a: 1 } }, { ...PAGE, key: 7 }, { ...PAGE, key: 'k'.repeat(101) }, { ...PAGE, html: '   ' }, { ...PAGE, html: 'x'.repeat(MAX_HTML_CHARS + 1) }]) {
      expect(readPageMessage(bad)).toBeNull()
    }
  })

  it('answers only real http(s) origins', () => {
    expect(isAnswerableOrigin(SENDER)).toBe(true)
    expect(isAnswerableOrigin('null')).toBe(false)
    expect(isAnswerableOrigin('file://')).toBe(false)
    expect(isAnswerableOrigin('https://news.example.com/path')).toBe(false)
  })

  it('says who sent the page only when the service found it is another site', () => {
    expect(senderMismatchLine('www.news.example.com', 'news.example.com', true)).toBeNull()
    expect(senderMismatchLine('evil.example', 'news.example.com', false)).toBe('This page was sent by evil.example, but says it is from news.example.com.')
    expect(senderMismatchLine(null, 'news.example.com', false)).toBe('This page was sent by an unknown site, but says it is from news.example.com.')
  })

  it('has a plain sentence for the new error codes', () => {
    expect(stageErrorMessage('key')).toMatch(/Make a new button in Settings/)
    expect(stageErrorMessage('origin')).toMatch(/did not say which site sent the page/)
  })
})

describe('ImportPage receiving a page', () => {
  it('takes the first valid message from the opener, answers only that sender and stages it', async () => {
    render(<ImportPage />)
    expect(screen.getByText('Waiting for the page from your browser…')).toBeInTheDocument()
    deliver(PAGE)
    expect(opener.postMessage).toHaveBeenCalledWith({ type: ACK_MESSAGE }, SENDER)
    await waitFor(() => expect(api.stageImport).toHaveBeenCalledWith({ url: PAGE.url, title: 'A story', html: '<p>Hello</p>', sender: SENDER, key: KEY }))
    await waitFor(() => expect(router.navigate).toHaveBeenCalledWith({ name: 'import', token: TOKEN }, { replace: true }))
  })

  it('ignores every message after the first accepted one', async () => {
    render(<ImportPage />)
    deliver(PAGE)
    deliver({ ...PAGE, url: 'https://other.example/' })
    deliver(PAGE)
    await waitFor(() => expect(api.stageImport).toHaveBeenCalledTimes(1))
    expect(opener.postMessage).toHaveBeenCalledTimes(1)
  })

  it('ignores messages of the wrong shape, from another window, or from an origin it cannot answer', async () => {
    render(<ImportPage />)
    deliver({ ...PAGE, type: 'something-else' })
    deliver(PAGE, SENDER, window)
    deliver(PAGE, SENDER, null)
    deliver(PAGE, 'null')
    deliver({ ...PAGE, html: 'x'.repeat(MAX_HTML_CHARS + 1) })
    expect(api.stageImport).not.toHaveBeenCalled()
    expect(opener.postMessage).not.toHaveBeenCalled()
    deliver(PAGE)
    await waitFor(() => expect(api.stageImport).toHaveBeenCalledTimes(1))
  })

  it('shows the service refusal when staging fails', async () => {
    api.stageImport.mockRejectedValue(new Error('Links to this computer or a private network are not accepted.'))
    render(<ImportPage />)
    deliver(PAGE)
    expect(await screen.findByRole('alert')).toHaveTextContent('private network')
  })

  it('explains what to do when nothing arrives', () => {
    vi.useFakeTimers()
    render(<ImportPage />)
    act(() => {
      vi.advanceTimersByTime(SLOW_AFTER_MS + 10)
    })
    expect(screen.getByText(/Save the page from your browser/)).toBeInTheDocument()
  })
})

describe('ImportPage confirming a page', () => {
  it('shows the host and the full address, the title and the preview as text', async () => {
    api.getStagedImport.mockResolvedValue(preview({ title: '<img src=x onerror="alert(1)">Breaking', excerpt: '<b>not bold</b>' }))
    const { container } = render(<ImportPage token={TOKEN} />)
    expect(await screen.findByRole('heading', { name: 'Add this page to Spyglass?' })).toBeInTheDocument()
    expect(screen.getByText('news.example.com')).toBeInTheDocument()
    expect(screen.getByText('https://news.example.com/2026/11/story?id=7')).toBeInTheDocument()
    expect(screen.getByText('<img src=x onerror="alert(1)">Breaking')).toBeInTheDocument()
    expect(screen.getByText('<b>not bold</b>')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(api.getStagedImport).toHaveBeenCalledWith(TOKEN, expect.anything())
  })

  it('says plainly, in its own row above the buttons, that another site sent the page', async () => {
    api.getStagedImport.mockResolvedValue(preview({ sender: 'evil.example', sender_matches: false }))
    render(<ImportPage token={TOKEN} />)
    const line = await screen.findByText('This page was sent by evil.example, but says it is from news.example.com.')
    const add = screen.getByRole('button', { name: 'Add to Spyglass' })
    // The line comes before the buttons in the page, and adding is still allowed (nothing to replace).
    expect(line.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByText(REPLACE_REFUSED_MESSAGE)).toBeNull()
  })

  it('says the sender is unknown when the service could not tell', async () => {
    api.getStagedImport.mockResolvedValue(preview({ sender: null, sender_matches: false }))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByText('This page was sent by an unknown site, but says it is from news.example.com.')).toBeInTheDocument()
  })

  it('replaces the Add button with the refusal when a page from another site would replace an existing item', async () => {
    api.getStagedImport.mockResolvedValue(preview({ sender: 'evil.example', sender_matches: false, existing_item_id: 9, replaces_existing: true, replace_refused: true }))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByText(REPLACE_REFUSED_MESSAGE)).toBeInTheDocument()
    expect(screen.getByText('This page was sent by evil.example, but says it is from news.example.com.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add to Spyglass' })).toBeNull()
    expect(screen.queryByText(/adding replaces its reader copy/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Discard' })).toBeEnabled()
  })

  it('follows the service when it refuses a replacement even though the sender looks like the same site', async () => {
    api.getStagedImport.mockResolvedValue(preview({ sender: 'bob.hosting.io', sender_matches: true, existing_item_id: 9, replaces_existing: true, replace_refused: true }))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByText(REPLACE_REFUSED_MESSAGE)).toBeInTheDocument()
    expect(screen.queryByText(/This page was sent by/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add to Spyglass' })).toBeNull()
  })

  it('still offers Add when the sender is the page itself and an item exists', async () => {
    api.getStagedImport.mockResolvedValue(preview({ existing_item_id: 9, replaces_existing: true }))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByText(/adding replaces its reader copy/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to Spyglass' })).toBeInTheDocument()
    expect(screen.queryByText(REPLACE_REFUSED_MESSAGE)).toBeNull()
  })

  it('does not name the sender when it is the page itself', async () => {
    render(<ImportPage token={TOKEN} />)
    await screen.findByRole('heading', { name: 'Add this page to Spyglass?' })
    expect(screen.queryByText(/This page was sent by/)).toBeNull()
  })

  it('adds the page, then offers Open in Spyglass and Close this window', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const closeSpy = vi.spyOn(window, 'close').mockImplementation(() => undefined)
    render(<ImportPage token={TOKEN} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add to Spyglass' })).toBeEnabled(), { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: 'Add to Spyglass' }))
    expect(await screen.findByText('Added. It will be judged in the next collection.')).toBeInTheDocument()
    expect(api.acceptStagedImport).toHaveBeenCalledWith(TOKEN)
    fireEvent.click(screen.getByRole('button', { name: 'Open in Spyglass' }))
    expect(openSpy).toHaveBeenCalledWith(expect.stringMatching(/#\/item\/42$/), '_blank', 'noopener')
    fireEvent.click(screen.getByRole('button', { name: 'Close this window' }))
    expect(closeSpy).toHaveBeenCalled()
  })

  it('keeps Add disabled for a moment after the preview appears, so a click meant for the sending page cannot land on it', async () => {
    vi.useFakeTimers()
    render(<ImportPage token={TOKEN} />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })
    const add = screen.getByRole('button', { name: 'Add to Spyglass' })
    expect(add).toBeDisabled()
    fireEvent.click(add)
    fireEvent.click(add)
    expect(api.acceptStagedImport).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ARM_AFTER_MS)
    })
    expect(screen.getByRole('button', { name: 'Add to Spyglass' })).toBeEnabled()
    expect(ARM_AFTER_MS).toBe(700)
  })

  it('lets Discard work at once', async () => {
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByRole('button', { name: 'Discard' })).toBeEnabled()
  })

  it('discards the page', async () => {
    render(<ImportPage token={TOKEN} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(await screen.findByText('Discarded. Nothing was added.')).toBeInTheDocument()
    expect(api.discardStagedImport).toHaveBeenCalledWith(TOKEN)
    expect(api.acceptStagedImport).not.toHaveBeenCalled()
  })

  it('says when an existing item will be replaced, and cannot add a page with no text', async () => {
    api.getStagedImport.mockResolvedValue(preview({ existing_item_id: 9, replaces_existing: true, word_count: 0, excerpt: '' }))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByText(/adding replaces its reader copy/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to Spyglass' })).toBeDisabled()
  })

  it('shows why when the page is no longer waiting', async () => {
    api.getStagedImport.mockRejectedValue(new Error('This page is no longer waiting. Send it again from your browser.'))
    render(<ImportPage token={TOKEN} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no longer waiting')
  })

  it('shows a fixed sentence for an error code and does not listen for messages', () => {
    render(<ImportPage error="address" />)
    expect(screen.getByRole('alert')).toHaveTextContent(stageErrorMessage('address'))
    deliver(PAGE)
    expect(api.stageImport).not.toHaveBeenCalled()
  })
})
