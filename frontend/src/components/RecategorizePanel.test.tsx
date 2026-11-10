// Tests for the Recategorize panel: kick the pass, review candidates, accept/discard.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RecategorizePanel } from './RecategorizePanel'

const CAND = {
  suggested_name: 'Robotics',
  size: 9,
  card_ids: [1, 2, 3],
  examples: ['Robot arm', 'Drone swarm'],
}

/** A stateful fetch stub: GET returns 'none' until a POST kick flips it to an 'ok' run. */
function stubFetch() {
  let kicked = false
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/recategorize/accept')) {
      return new Response(JSON.stringify({ name: 'Robotics', assigned: 3 }), { status: 200 })
    }
    if (url.includes('/api/recategorize') && init?.method === 'POST') {
      kicked = true
      return new Response(JSON.stringify({ status: 'started' }), { status: 202 })
    }
    if (url.includes('/api/recategorize')) {
      const body = kicked
        ? { status: 'ok', assigned: 0, candidates: [CAND] }
        : { status: 'none', candidates: [] }
      return new Response(JSON.stringify(body), { status: 200 })
    }
    return new Response(JSON.stringify({}), { status: 200 })
  })
}

describe('RecategorizePanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', stubFetch())
    // The Recategorize button confirms first (expensive AI pass); default the prompt to accept.
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows a Recategorize button', async () => {
    render(<RecategorizePanel onAccepted={() => {}} />)
    expect(await screen.findByRole('button', { name: /recategorize/i })).toBeInTheDocument()
  })

  it('kicks the pass and shows the discovered candidates', async () => {
    render(<RecategorizePanel onAccepted={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /recategorize/i }))
    expect(await screen.findByText('Robotics')).toBeInTheDocument()
    expect(screen.getByText(/9 articles/i)).toBeInTheDocument()
  })

  it('does not kick the pass when the confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    render(<RecategorizePanel onAccepted={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /recategorize/i }))
    // No POST /api/recategorize was issued (only the mount GET).
    expect(stub.mock.calls.some((c) => String(c[0]).includes('/recategorize') && c[1]?.method === 'POST')).toBe(false)
  })

  it('accepts a candidate: POSTs accept, removes it, and notifies the parent', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    const onAccepted = vi.fn()
    render(<RecategorizePanel onAccepted={onAccepted} />)
    fireEvent.click(await screen.findByRole('button', { name: /recategorize/i }))
    fireEvent.click(await screen.findByRole('button', { name: /accept robotics/i }))
    await waitFor(() => {
      const accept = stub.mock.calls.find((c) => String(c[0]).includes('/accept'))
      expect(accept).toBeDefined()
      expect(JSON.parse(String(accept![1]!.body))).toEqual({ name: 'Robotics', card_ids: [1, 2, 3] })
    })
    expect(onAccepted).toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByText('Robotics')).not.toBeInTheDocument())
  })

  it('discards a candidate without calling accept', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    render(<RecategorizePanel onAccepted={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /recategorize/i }))
    await screen.findByText('Robotics')
    fireEvent.click(screen.getByRole('button', { name: /discard robotics/i }))
    await waitFor(() => expect(screen.queryByText('Robotics')).not.toBeInTheDocument())
    expect(stub.mock.calls.some((c) => String(c[0]).includes('/accept'))).toBe(false)
  })
})
