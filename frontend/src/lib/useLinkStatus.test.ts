// The closing window tells the service, so the link can end with Spyglass.
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useLinkStatus } from './useLinkStatus'

afterEach(() => vi.unstubAllGlobals())

describe('useLinkStatus', () => {
  it('sends a beacon when the window closes', async () => {
    const status = { linked: true, linked_at: 'x', last_seen: 'x', waiting: false }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(status))))
    const beacon = vi.fn(() => true)
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
    const { result } = renderHook(() => useLinkStatus())
    await waitFor(() => expect(result.current.status?.linked).toBe(true))
    window.dispatchEvent(new Event('pagehide'))
    expect(beacon).toHaveBeenCalledWith('/api/link/window-closed', expect.any(Blob))
  })
})
