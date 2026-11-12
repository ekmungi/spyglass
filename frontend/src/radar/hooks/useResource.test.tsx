// Tests for useResource: cached answers show at once, a refetch replaces them only when they
// differ, a hidden page refetches when shown again, and a failed refresh keeps what is on screen.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearResourceCache, STALE_AFTER_MS, useResource } from './useResource'

beforeEach(() => clearResourceCache())
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('useResource', () => {
  it('loads, then shows the cached answer at once with a quiet refresh on the next visit', async () => {
    let answer = { n: 1 }
    const loader = vi.fn(async () => answer)
    const first = renderHook(() => useResource('k', loader))
    expect(first.result.current.loading).toBe(true)
    await waitFor(() => expect(first.result.current.data).toEqual({ n: 1 }))
    first.unmount()

    answer = { n: 2 }
    const second = renderHook(() => useResource('k', loader))
    expect(second.result.current.data).toEqual({ n: 1 })
    expect(second.result.current.loading).toBe(false)
    expect(second.result.current.refreshing).toBe(true)
    await waitFor(() => expect(second.result.current.data).toEqual({ n: 2 }))
    expect(second.result.current.refreshing).toBe(false)
  })

  it('keeps the same data object when the refreshed answer is identical', async () => {
    const loader = vi.fn(async () => ({ n: 1, list: [1, 2] }))
    const view = renderHook(() => useResource('k', loader))
    await waitFor(() => expect(view.result.current.data).toBeDefined())
    const before = view.result.current.data
    act(() => view.result.current.reload())
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2))
    await act(async () => undefined)
    expect(view.result.current.data).toBe(before)
  })

  it('keeps the cached answer when a refresh fails, and reports the error', async () => {
    let fail = false
    const loader = vi.fn(async () => {
      if (fail) throw new Error('down')
      return 'fine'
    })
    const view = renderHook(() => useResource('k', loader))
    await waitFor(() => expect(view.result.current.data).toBe('fine'))
    fail = true
    act(() => view.result.current.reload())
    await waitFor(() => expect(view.result.current.error).toBeInstanceOf(Error))
    expect(view.result.current.data).toBe('fine')
  })

  it('does not fetch while inactive and fetches when it becomes active', async () => {
    const loader = vi.fn(async () => 'x')
    const view = renderHook(({ active }) => useResource('k', loader, { active }), { initialProps: { active: false } })
    await act(async () => undefined)
    expect(loader).not.toHaveBeenCalled()
    view.rerender({ active: true })
    await waitFor(() => expect(view.result.current.data).toBe('x'))
  })

  it('refetches on window focus only after the answer is stale', async () => {
    const loader = vi.fn(async () => 'x')
    const view = renderHook(() => useResource('k', loader, { revalidateOnFocus: true }))
    await waitFor(() => expect(view.result.current.data).toBe('x'))
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    expect(loader).toHaveBeenCalledTimes(1) // still fresh

    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + STALE_AFTER_MS + 1000)
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2))
  })

  it('does nothing for a null key', async () => {
    const loader = vi.fn(async () => 'x')
    const view = renderHook(() => useResource(null, loader))
    await act(async () => undefined)
    expect(loader).not.toHaveBeenCalled()
    expect(view.result.current.loading).toBe(false)
    expect(view.result.current.data).toBeUndefined()
  })

  it('setData updates the data and the cache', async () => {
    const loader = vi.fn(async () => 1)
    const first = renderHook(() => useResource<number>('k', loader))
    await waitFor(() => expect(first.result.current.data).toBe(1))
    act(() => first.result.current.setData(() => 5))
    expect(first.result.current.data).toBe(5)
    first.unmount()
    const second = renderHook(() => useResource<number>('k', loader))
    expect(second.result.current.data).toBe(5)
  })
})
