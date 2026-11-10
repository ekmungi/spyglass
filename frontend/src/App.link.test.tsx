// The app routes conversations about items through the linked Claude session.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './lib/api'
import { makeCard } from './test/fixtures'

vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const NOW = new Date().toISOString()

function stubFetch(linked: boolean, failFirstStatus = false) {
  let statusReads = 0
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
    if (url.includes('/api/link/open')) return respond({ opened: true })
    if (url.includes('/api/link')) {
      statusReads += 1
      if (failFirstStatus && statusReads === 1) return new Response('down', { status: 503 })
      return respond({ linked, linked_at: linked ? NOW : null, last_seen: linked ? NOW : null,
        waiting: false })
    }
    if (url.includes('/api/refresh')) return respond({ refreshed: true, sources: 0 })
    if (url.includes('/fulltext')) return respond({ status: 'absent' })
    if (url.includes('/api/categories')) return respond([])
    if (url.includes('/api/runs')) return respond([])
    if (url.includes('/api/briefs')) return respond([])
    if (url.includes('/api/cards/1')) return respond(makeCard({ id: 1, title: 'First card' }))
    if (url.includes('/api/cards')) return respond([makeCard({ id: 1, title: 'First card' })])
    if (url.includes('/api/selection')) return respond({ card_ids: [1] })
    return respond({})
  })
}

function calls(): Array<{ url: string; body: unknown }> {
  return (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => ({
    url: String(c[0]),
    body: c[1]?.body ? JSON.parse(String(c[1].body)) : undefined,
  }))
}

describe('App and the linked session', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
  })
  afterEach(() => vi.unstubAllGlobals())

  it('opens a new linked session about the item when none is linked', async () => {
    vi.stubGlobal('fetch', stubFetch(false))
    render(<App />)
    expect(await screen.findByText('No linked Claude session')).toBeInTheDocument()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Open in Claude' }))[0])
    await waitFor(() =>
      expect(calls().find((c) => c.url.includes('/api/link/open'))?.body).toEqual({
        card_ids: [1],
        task: null,
      }),
    )
  })

  it('selects the item and copies its code when a session is linked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('fetch', stubFetch(true))
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<App />)
    expect(await screen.findByText(/^Linked to Claude/)).toBeInTheDocument()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Open in Claude' }))[0])
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('#1'))
    expect(calls().some((c) => c.url.includes('/api/link/open'))).toBe(false)
    expect(
      await screen.findByText('Copied for your linked Claude session: paste it there'),
    ).toBeInTheDocument()
  })

  it('opens a linked session from the header', async () => {
    vi.stubGlobal('fetch', stubFetch(false))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Open a linked Claude session' }))
    await waitFor(() => expect(calls().some((c) => c.url.includes('/api/link/open'))).toBe(true))
  })

  it('does not wipe a selection when the Workspace opens', async () => {
    vi.stubGlobal('fetch', stubFetch(false))
    render(<App />)
    await screen.findByText('First card')
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(calls().some((c) => c.url.includes('/api/selection'))).toBe(false)
  })

  it('keeps the launched items for the linked session after the ticks clear', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('fetch', stubFetch(true))
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<App />)
    expect(await screen.findByText(/^Linked to Claude/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select First card' }))
    fireEvent.click(screen.getByRole('button', { name: /open claude code/i }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('#1'))
    await new Promise((resolve) => setTimeout(resolve, 450))
    const posted = calls().filter((c) => c.url.includes('/api/selection'))
    expect(posted.at(-1)?.body).toEqual({ card_ids: [1] })
  })

  it('asks for the link before routing when the last read failed', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('fetch', stubFetch(true, true))
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<App />)
    await screen.findByText('First card')
    fireEvent.click((await screen.findAllByRole('button', { name: 'Open in Claude' }))[0])
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('#1'))
    expect(calls().some((c) => c.url.includes('/api/link/open'))).toBe(false)
  })
})
