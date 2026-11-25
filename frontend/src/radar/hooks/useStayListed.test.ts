// Tests for useStayListed: a changed row is remembered with the place it had when first changed, a later
// change keeps that first place, and release forgets every row.
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useStayListed } from './useStayListed'

describe('useStayListed', () => {
  it('starts with no row kept in place', () => {
    const { result } = renderHook(() => useStayListed<number, string>())
    expect(result.current.pinned.size).toBe(0)
  })

  it('keeps the place a row had when it was first changed', () => {
    const { result } = renderHook(() => useStayListed<number, string>())
    act(() => result.current.pin(7, 'others'))
    act(() => result.current.pin(7, 'working'))
    expect(result.current.pinned.get(7)).toBe('others')
  })

  it('forgets every row on release', () => {
    const { result } = renderHook(() => useStayListed<string>())
    act(() => {
      result.current.pin('a', true)
      result.current.pin('b', true)
    })
    expect([...result.current.pinned.keys()]).toEqual(['a', 'b'])
    act(() => result.current.release())
    expect(result.current.pinned.size).toBe(0)
  })
})
