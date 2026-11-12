// Tests for page-change transitions: which route changes count as a new screen, and that a view
// transition runs only for those, only where supported, and never under reduced motion.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { navigate } from '../router'
import { screenKey, useShownRoute } from './useShownRoute'

type Start = (update: () => void) => { finished: Promise<void>; ready: Promise<void> }

/** A stand-in for document.startViewTransition: like the browser, it runs the update a moment later. */
function installViewTransitions(): ReturnType<typeof vi.fn<Start>> {
  const start = vi.fn<Start>((update) => {
    const finished = Promise.resolve().then(update)
    return { finished, ready: finished }
  })
  Object.defineProperty(document, 'startViewTransition', { configurable: true, writable: true, value: start })
  return start
}

beforeEach(() => window.history.replaceState(null, '', '/#/today'))

afterEach(() => {
  delete (document as { startViewTransition?: unknown }).startViewTransition
  document.documentElement.removeAttribute('data-page-transition')
  vi.unstubAllGlobals()
})

describe('screenKey', () => {
  it('ignores the query of the same page', () => {
    expect(screenKey({ name: 'feed', params: {} })).toBe(screenKey({ name: 'feed', params: { section: 'health', saved: '1' } }))
    expect(screenKey({ name: 'settings' })).toBe(screenKey({ name: 'settings', section: 'bring-in' }))
  })

  it('tells pages, days and items apart', () => {
    expect(screenKey({ name: 'today' })).not.toBe(screenKey({ name: 'today', day: '2026-11-11' }))
    expect(screenKey({ name: 'item', id: 1 })).not.toBe(screenKey({ name: 'item', id: 2 }))
    expect(screenKey({ name: 'watch' })).not.toBe(screenKey({ name: 'feed', params: {} }))
  })
})

describe('useShownRoute', () => {
  it('follows the address at once where view transitions are not supported', () => {
    const { result } = renderHook(() => useShownRoute())
    act(() => navigate({ name: 'watch' }))
    expect(result.current.name).toBe('watch')
  })

  it('keeps the old page until the transition swaps it, with the root marked meanwhile', async () => {
    const start = installViewTransitions()
    let markedDuringUpdate: string | undefined
    let shownDuringCapture: string | undefined
    const { result } = renderHook(() => useShownRoute())
    start.mockImplementation((update) => {
      markedDuringUpdate = document.documentElement.dataset.pageTransition
      shownDuringCapture = result.current.name
      const finished = Promise.resolve().then(update)
      return { finished, ready: finished }
    })
    await act(async () => navigate({ name: 'watch' }))
    expect(start).toHaveBeenCalledTimes(1)
    expect(markedDuringUpdate).toBe('true')
    expect(shownDuringCapture).toBe('today')
    expect(result.current.name).toBe('watch')
  })

  it('clears the root mark when the transition finishes', async () => {
    installViewTransitions()
    renderHook(() => useShownRoute())
    await act(async () => navigate({ name: 'watch' }))
    await act(async () => undefined)
    expect(document.documentElement.dataset.pageTransition).toBeUndefined()
  })

  it('does not animate when only the query of the same page changes', () => {
    window.history.replaceState(null, '', '/#/feed')
    const start = installViewTransitions()
    const { result } = renderHook(() => useShownRoute())
    act(() => navigate({ name: 'feed', params: { section: 'health' } }, { replace: true }))
    expect(start).not.toHaveBeenCalled()
    expect(result.current).toEqual({ name: 'feed', params: { section: 'health' } })
  })

  it('does not animate under reduced motion', () => {
    const start = installViewTransitions()
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }))
    const { result } = renderHook(() => useShownRoute())
    act(() => navigate({ name: 'watch' }))
    expect(start).not.toHaveBeenCalled()
    expect(result.current.name).toBe('watch')
  })

  it('does not wait for a frame when the page is hidden', () => {
    const start = installViewTransitions()
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const { result } = renderHook(() => useShownRoute())
    act(() => navigate({ name: 'watch' }))
    expect(start).not.toHaveBeenCalled()
    expect(result.current.name).toBe('watch')
    visibility.mockRestore()
  })

  it('still shows the new page if starting the transition throws', async () => {
    const start = installViewTransitions()
    start.mockImplementation(() => {
      throw new Error('InvalidStateError')
    })
    const { result } = renderHook(() => useShownRoute())
    await act(async () => navigate({ name: 'watch' }))
    expect(result.current.name).toBe('watch')
    expect(document.documentElement.dataset.pageTransition).toBeUndefined()
  })
})
