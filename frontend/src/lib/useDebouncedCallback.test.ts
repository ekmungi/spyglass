// Tests for the debounce hook: coalesces rapid calls into one
// trailing invocation, used to collapse a burst of thumbs into one background reload.
import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedCallback } from './useDebouncedCallback'

describe('useDebouncedCallback', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('does not fire before the delay elapses', () => {
    const fn = vi.fn()
    const { result } = renderHook(() => useDebouncedCallback(fn, 600))
    result.current()
    vi.advanceTimersByTime(599)
    expect(fn).not.toHaveBeenCalled()
  })

  it('invokes the wrapped fn exactly once after the delay, even with 3 rapid calls', () => {
    const fn = vi.fn()
    const { result } = renderHook(() => useDebouncedCallback(fn, 600))
    result.current()
    result.current()
    result.current()
    vi.advanceTimersByTime(600)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('clears the pending timer on unmount so it never fires late', () => {
    const fn = vi.fn()
    const { result, unmount } = renderHook(() => useDebouncedCallback(fn, 600))
    result.current()
    unmount()
    vi.advanceTimersByTime(600)
    expect(fn).not.toHaveBeenCalled()
  })

  it('always uses the latest fn passed in, even if it changed after scheduling', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { result, rerender } = renderHook(({ fn }) => useDebouncedCallback(fn, 600), {
      initialProps: { fn: first },
    })
    result.current()
    rerender({ fn: second })
    vi.advanceTimersByTime(600)
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })
})
