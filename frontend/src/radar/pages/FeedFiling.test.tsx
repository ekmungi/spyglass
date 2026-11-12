// Tests for the Feed's To file filter and view: the count on the chip, the Waiting group, File now
// (success, no vault set, an empty queue) and See the request. The sample service stands in for the
// real one; a wrapper records the calls and can make the service refuse.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { OPENED_TOAST } from '../claude/ClaudeCodeDialog'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { setFilingConfigured } from '../state/filingConfigured'
import { resetFilingState } from '../state/filingState'
import { dismissToast, subscribeToasts, type ToastMessage } from '../ui/toastStore'
import { FeedPage } from './FeedPage'

let calls: string[] = []
let refuseOpen: Response | null = null
let toasts: readonly ToastMessage[] = []
let unsubscribe: () => void

beforeEach(() => {
  resetMockState()
  resetFilingState()
  // These tests are about an install where filing is set up.
  setFilingConfigured(true)
  clearResourceCache()
  clearFeedCache()
  calls = []
  refuseOpen = null
  window.history.replaceState(null, '', '/#/feed')
  setFetchForTesting(async (url, init) => {
    const path = new URL(url, 'http://x').pathname.replace('/api/radar', '')
    calls.push(`${(init?.method ?? 'GET').toUpperCase()} ${path}`)
    if (path === '/filing/open' && refuseOpen) return refuseOpen
    return mockFetch(url, init)
  })
  unsubscribe = subscribeToasts((list) => {
    toasts = list
  })
})

afterEach(() => {
  toasts.forEach((entry) => dismissToast(entry.id))
  unsubscribe()
  cleanup()
  setFetchForTesting(null)
})

/** Queue some sample items through the sample service, as a click on File in vault would. */
async function queue(...ids: number[]) {
  for (const id of ids) await mockFetch(`/api/radar/items/${id}/file`, { method: 'POST', body: '{}' })
}

/** Wait until the Waiting group's heading says `n` items. */
async function expectWaiting(n: number) {
  const heading = await screen.findByRole('heading', { name: 'Waiting' })
  await waitFor(() => expect(heading.parentElement).toHaveTextContent(`${n} ${n === 1 ? 'item' : 'items'}`))
}

describe('the To file filter', () => {
  it('sits beside Saved and From you, shows the count when above zero, and puts filing=waiting in the address', async () => {
    await queue(101, 102)
    render(<FeedPage params={{}} />)
    const chip = await screen.findByRole('button', { name: /To file/ })
    await waitFor(() => expect(chip).toHaveTextContent('2'))
    const names = screen.getAllByRole('button').map((button) => button.textContent ?? '')
    const index = names.findIndex((name) => name.startsWith('To file'))
    expect(names[index - 1]).toBe('From you')
    fireEvent.click(chip)
    await waitFor(() => expect(window.location.hash).toBe('#/feed?filing=waiting'))
  })

  it('shows no number while nothing waits', async () => {
    render(<FeedPage params={{}} />)
    const chip = await screen.findByRole('button', { name: /To file/ })
    await waitFor(() => expect(calls).toContain('GET /filing'))
    expect(chip.textContent).toBe('To file')
  })

  it('lists only the waiting items, under the status line and the Waiting heading', async () => {
    await queue(101, 102)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await expectWaiting(2)
    expect(await screen.findByText(/Last run/)).toHaveAttribute('role', 'status')
    await waitFor(() => expect(screen.getAllByText(/Waiting to be filed/)).toHaveLength(2))
    expect(calls).toContain('GET /feed')
    expect(await screen.findByRole('button', { name: 'File now' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'See the request' })).toBeInTheDocument()
  })

  it('says "1 item" for a queue of one', async () => {
    await queue(101)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await expectWaiting(1)
  })

  it('drops a row from the list as soon as it leaves the queue', async () => {
    await queue(101, 102)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await waitFor(() => expect(screen.getAllByText(/Waiting to be filed/)).toHaveLength(2))
    await mockFetch('/api/radar/items/101/file', { method: 'DELETE' })
    const { unqueueItem } = await import('../state/filingState')
    await unqueueItem(101, { quiet: true })
    await waitFor(() => expect(screen.getAllByText(/Waiting to be filed/)).toHaveLength(1))
    await expectWaiting(1)
  })
})

describe('File now', () => {
  it('opens one session through POST /filing/open and tells the reader to finish there', async () => {
    await queue(101, 102)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'File now' }))
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(OPENED_TOAST))
    expect(calls.filter((call) => call === 'POST /filing/open')).toHaveLength(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the plain error when no vault is set', async () => {
    await queue(101)
    refuseOpen = new Response(JSON.stringify({ detail: 'No vault folder is set in Spyglass, so Claude Code cannot be opened in it.' }), { status: 409, headers: { 'Content-Type': 'application/json' } })
    render(<FeedPage params={{ filing: 'waiting' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'File now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No vault folder is set in Spyglass, so Claude Code cannot be opened in it.')
    expect(toasts.map((entry) => entry.message)).not.toContain(OPENED_TOAST)
    expect(screen.getByRole('button', { name: 'File now' })).toBeEnabled()
  })

  it('treats a request delivered as a hand-off like any other opening', async () => {
    await queue(101)
    refuseOpen = new Response(JSON.stringify({ opened: true, delivery: 'handoff' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    render(<FeedPage params={{ filing: 'waiting' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'File now' }))
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(OPENED_TOAST))
  })
})

describe('See the request', () => {
  it('shows the exact text and the vault without opening anything, and hides it again', async () => {
    await queue(101, 102)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    fireEvent.click(await screen.findByRole('button', { name: 'See the request' }))
    const box = await screen.findByLabelText('The request sent to Claude Code')
    expect(box).toHaveTextContent('2 items are waiting to be filed in this vault.')
    expect(box).toHaveTextContent('spyglass-file')
    expect(screen.getByText(/Opens in /)).toBeInTheDocument()
    expect(calls).not.toContain('POST /filing/open')
    fireEvent.click(screen.getByRole('button', { name: 'See the request' }))
    expect(screen.queryByLabelText('The request sent to Claude Code')).not.toBeInTheDocument()
  })
})

describe('an empty queue', () => {
  it('says nothing is waiting, offers no File now, and lists nothing', async () => {
    render(<FeedPage params={{ filing: 'waiting' }} />)
    const bar = await screen.findByText(/Nothing is waiting to be filed/)
    expect(bar).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'File now' })).not.toBeInTheDocument()
    expect(within(document.body).queryAllByText(/Waiting to be filed/)).toHaveLength(0)
  })

  it('shows that one message only, not the Feed’s own "Nothing matches these filters" below it', async () => {
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await screen.findByText(/Nothing is waiting to be filed/)
    await waitFor(() => expect(screen.queryByRole('status', { name: 'Loading the feed' })).not.toBeInTheDocument())
    expect(screen.queryByText('Nothing matches these filters')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()
  })
})
