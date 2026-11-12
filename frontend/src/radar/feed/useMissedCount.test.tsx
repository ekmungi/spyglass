// Tests for useMissedCount: the number on the Missed chip comes from the service's total, asks for one
// row only, waits while the Feed is hidden, and keeps the last number when the request fails.
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearMissedCount, useMissedCount } from './useMissedCount'

afterEach(() => {
  cleanup()
  clearMissedCount()
  setFetchForTesting(null)
})

/** Answer every request with `total` and record the addresses asked. */
function serve(total: number): string[] {
  const urls: string[] = []
  setFetchForTesting(async (input) => {
    urls.push(String(input))
    return new Response(JSON.stringify({ items: [], next_before: null, total }), { status: 200 })
  })
  return urls
}

describe('useMissedCount', () => {
  it('reads the total of a one-row Missed request', async () => {
    const urls = serve(7)
    const view = renderHook(() => useMissedCount(true))
    await waitFor(() => expect(view.result.current).toBe(7))
    expect(urls[0]).toContain('missed=true')
    expect(urls[0]).toContain('limit=1')
  })

  it('starts a new Feed with the last number read, so the chip does not change width', async () => {
    serve(5)
    const first = renderHook(() => useMissedCount(true))
    await waitFor(() => expect(first.result.current).toBe(5))
    first.unmount()
    setFetchForTesting(() => new Promise<Response>(() => undefined))
    expect(renderHook(() => useMissedCount(true)).result.current).toBe(5)
  })

  it('does not ask while the Feed is hidden, and asks again when it is shown', async () => {
    const urls = serve(3)
    const view = renderHook(({ active }) => useMissedCount(active), { initialProps: { active: false } })
    expect(urls).toHaveLength(0)
    expect(view.result.current).toBe(0)
    view.rerender({ active: true })
    await waitFor(() => expect(view.result.current).toBe(3))
  })

  it('keeps the last number when a request fails', async () => {
    serve(4)
    const view = renderHook(({ active }) => useMissedCount(active), { initialProps: { active: true } })
    await waitFor(() => expect(view.result.current).toBe(4))
    setFetchForTesting(async () => new Response('{"detail":"down"}', { status: 500 }))
    view.rerender({ active: false })
    view.rerender({ active: true })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(view.result.current).toBe(4)
  })
})
