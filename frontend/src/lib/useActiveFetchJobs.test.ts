// Tests for the dashboard-wide active-fetch poller: drives the list-row
// pending markers, and polls ONLY while something is actually in flight.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import { ACTIVE_JOBS_POLL_MS, useActiveFetchJobs } from './useActiveFetchJobs'

/** Advance fake timers and flush the promise callbacks they schedule, inside act(). */
async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useActiveFetchJobs', () => {
  it('reads the active set once on mount so a reload mid-fetch still shows markers', async () => {
    const getActive = vi.spyOn(api, 'getActiveFetchJobs').mockResolvedValue([4, 9])
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    expect(getActive).toHaveBeenCalledTimes(1)
    expect([...result.current.fetchingIds]).toEqual([4, 9])
  })

  it('keeps polling while at least one job is in flight', async () => {
    const getActive = vi.spyOn(api, 'getActiveFetchJobs').mockResolvedValue([4])
    renderHook(() => useActiveFetchJobs())
    await tick()
    await tick(ACTIVE_JOBS_POLL_MS)
    await tick(ACTIVE_JOBS_POLL_MS)
    expect(getActive).toHaveBeenCalledTimes(3)
  })

  it('stops polling once nothing is in flight', async () => {
    // The idle dashboard must not sit on a 2s timer forever.
    const getActive = vi
      .spyOn(api, 'getActiveFetchJobs')
      .mockResolvedValueOnce([4])
      .mockResolvedValue([])
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    await tick(ACTIVE_JOBS_POLL_MS)
    expect(getActive).toHaveBeenCalledTimes(2)
    expect(result.current.fetchingIds.size).toBe(0)

    await tick(ACTIVE_JOBS_POLL_MS * 5)
    expect(getActive).toHaveBeenCalledTimes(2)
  })

  it('refresh() restarts the loop after it went idle', async () => {
    // How the reader tells the list "I just queued one" without the list having to guess.
    const getActive = vi
      .spyOn(api, 'getActiveFetchJobs')
      .mockResolvedValueOnce([])
      .mockResolvedValue([12])
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    expect(getActive).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.refresh()
    })
    await tick()
    expect(getActive).toHaveBeenCalledTimes(2)
    expect([...result.current.fetchingIds]).toEqual([12])
  })

  it('keeps the same Set instance while the ids are unchanged', async () => {
    // WorkspaceView re-filters the whole corpus on every render; handing back a fresh Set
    // each poll would re-run that on a 2s timer for nothing.
    vi.spyOn(api, 'getActiveFetchJobs').mockResolvedValue([4])
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    const first = result.current.fetchingIds
    await tick(ACTIVE_JOBS_POLL_MS)
    expect(result.current.fetchingIds).toBe(first)
  })

  it('replaces the Set when the ids actually change', async () => {
    vi.spyOn(api, 'getActiveFetchJobs')
      .mockResolvedValueOnce([4])
      .mockResolvedValue([4, 5])
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    const first = result.current.fetchingIds
    await tick(ACTIVE_JOBS_POLL_MS)
    expect(result.current.fetchingIds).not.toBe(first)
    expect([...result.current.fetchingIds]).toEqual([4, 5])
  })

  it('stops polling on unmount', async () => {
    const getActive = vi.spyOn(api, 'getActiveFetchJobs').mockResolvedValue([4])
    const { unmount } = renderHook(() => useActiveFetchJobs())
    await tick()
    const before = getActive.mock.calls.length
    unmount()
    await tick(ACTIVE_JOBS_POLL_MS * 3)
    expect(getActive).toHaveBeenCalledTimes(before)
  })

  it('survives a failing poll without wedging the dashboard', async () => {
    vi.spyOn(api, 'getActiveFetchJobs').mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useActiveFetchJobs())
    await tick()
    expect(result.current.fetchingIds.size).toBe(0)
  })
})
