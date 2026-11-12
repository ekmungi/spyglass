// Tests for the motion helpers: reading a duration token, and keeping a closing element mounted
// for exactly its exit duration.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { motionMs, parseDurationMs, prefersReducedMotion } from './motion'
import { usePresence } from './usePresence'

function setToken(name: string, value: string) {
  document.documentElement.style.setProperty(name, value)
}

afterEach(() => {
  document.documentElement.removeAttribute('style')
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('parseDurationMs', () => {
  it('reads milliseconds and seconds', () => {
    expect(parseDurationMs('200ms')).toBe(200)
    expect(parseDurationMs(' 0.28s ')).toBe(280)
    expect(parseDurationMs('0ms')).toBe(0)
  })

  it('treats an empty or unreadable value as no motion', () => {
    expect(parseDurationMs('')).toBe(0)
    expect(parseDurationMs('fast')).toBe(0)
    expect(parseDurationMs('-50ms')).toBe(0)
  })
})

describe('motionMs', () => {
  it('reads a duration token from the document', () => {
    setToken('--dur', '200ms')
    expect(motionMs('--dur')).toBe(200)
  })

  it('is zero when the token is not defined (tests, or styles not loaded)', () => {
    expect(motionMs('--dur-slow')).toBe(0)
  })

  it('is zero under reduced motion even if a token says otherwise', () => {
    setToken('--dur', '200ms')
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }))
    expect(prefersReducedMotion()).toBe(true)
    expect(motionMs('--dur')).toBe(0)
  })
})

describe('usePresence', () => {
  beforeEach(() => vi.useFakeTimers())

  it('mounts at once when opened', () => {
    const { result } = renderHook(({ open }) => usePresence(open, '--dur'), { initialProps: { open: true } })
    expect(result.current).toEqual({ mounted: true, state: 'open' })
  })

  it('stays unmounted while closed', () => {
    const { result } = renderHook(({ open }) => usePresence(open, '--dur'), { initialProps: { open: false } })
    expect(result.current).toEqual({ mounted: false, state: 'closed' })
  })

  it('unmounts in the same render when there is no exit duration', () => {
    const { result, rerender } = renderHook(({ open }) => usePresence(open, '--dur'), { initialProps: { open: true } })
    rerender({ open: false })
    expect(result.current).toEqual({ mounted: false, state: 'closed' })
  })

  it('keeps a closing element mounted, marked closed, for its exit duration', () => {
    setToken('--dur', '200ms')
    const { result, rerender } = renderHook(({ open }) => usePresence(open, '--dur'), { initialProps: { open: true } })
    rerender({ open: false })
    expect(result.current).toEqual({ mounted: true, state: 'closed' })
    act(() => vi.advanceTimersByTime(199))
    expect(result.current.mounted).toBe(true)
    act(() => vi.advanceTimersByTime(1))
    expect(result.current).toEqual({ mounted: false, state: 'closed' })
  })

  it('reopening during the exit cancels the unmount', () => {
    setToken('--dur', '200ms')
    const { result, rerender } = renderHook(({ open }) => usePresence(open, '--dur'), { initialProps: { open: true } })
    rerender({ open: false })
    act(() => vi.advanceTimersByTime(100))
    rerender({ open: true })
    act(() => vi.advanceTimersByTime(500))
    expect(result.current).toEqual({ mounted: true, state: 'open' })
  })
})
