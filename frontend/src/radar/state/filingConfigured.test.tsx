// Tests for the "is filing set up" flag: read once from GET /filing, a missing field or a missing
// route counts as not set up, nothing is true before the answer arrives, and a failed request can be retried.
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { resetFilingConfigured, useFilingConfigured } from './filingConfigured'

let calls = 0

/** Shows what the hook says. */
function Probe() {
  return <p>{useFilingConfigured() ? 'on' : 'off'}</p>
}

/** Serve GET /filing with `body` (or the given status) and count the requests. */
function serve(body: unknown, status = 200) {
  calls = 0
  setFetchForTesting(async () => {
    calls += 1
    return new Response(JSON.stringify(body), { status })
  })
}

beforeEach(() => resetFilingConfigured())
afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('the filing flag', () => {
  it('is off before the answer arrives and on when status.configured is true, with one request for any number of readers', async () => {
    serve({ count: 0, waiting: [], status: { configured: true, mode: 'off', state: 'idle', last_run: null, next_retry: null, line: '' } })
    render(
      <>
        <Probe />
        <Probe />
      </>,
    )
    expect(screen.getAllByText('off')).toHaveLength(2)
    await waitFor(() => expect(screen.getAllByText('on')).toHaveLength(2))
    expect(calls).toBe(1)
  })

  it('is off when the field is missing or false', async () => {
    serve({ count: 0, waiting: [], status: { mode: 'off', state: 'idle', last_run: null, next_retry: null, line: '' } })
    render(<Probe />)
    await waitFor(() => expect(calls).toBe(1))
    await act(async () => undefined)
    expect(screen.getByText('off')).toBeInTheDocument()
    cleanup()
    resetFilingConfigured()
    serve({ count: 0, waiting: [], status: { configured: false } })
    render(<Probe />)
    await waitFor(() => expect(calls).toBe(1))
    await act(async () => undefined)
    expect(screen.getByText('off')).toBeInTheDocument()
  })

  it('is off for a service without the filing routes, and is not asked again', async () => {
    serve({ detail: 'Not found' }, 404)
    const first = render(<Probe />)
    await waitFor(() => expect(calls).toBe(1))
    await act(async () => undefined)
    first.unmount()
    render(<Probe />)
    await act(async () => undefined)
    expect(screen.getByText('off')).toBeInTheDocument()
    expect(calls).toBe(1)
  })

  it('stays unknown after a network failure and asks again the next time', async () => {
    setFetchForTesting(async () => {
      throw new TypeError('network down')
    })
    const first = render(<Probe />)
    await act(async () => undefined)
    first.unmount()
    serve({ count: 0, waiting: [], status: { configured: true } })
    render(<Probe />)
    await waitFor(() => expect(screen.getByText('on')).toBeInTheDocument())
    expect(calls).toBe(1)
  })
})
