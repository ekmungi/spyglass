// Tests for the hash router: parse/build round trips, navigation, Back, and scroll memory.
import { afterEach, describe, expect, it } from 'vitest'
import { arrivedByHistoryStep, buildHash, clearScrollMemory, getScroll, goBack, navigate, parseHash, saveScroll, type Route } from './router'
import { restoreScroll } from './shell/scroll'

afterEach(() => {
  clearScrollMemory()
  window.history.replaceState(null, '', '/')
})

describe('parseHash', () => {
  it('parses every route', () => {
    expect(parseHash('#/today')).toEqual({ name: 'today' })
    expect(parseHash('#/today/2026-11-12')).toEqual({ name: 'today', day: '2026-11-12' })
    expect(parseHash('#/item/42')).toEqual({ name: 'item', id: 42 })
    expect(parseHash('#/feed?section=health&tier=all')).toEqual({ name: 'feed', params: { section: 'health', tier: 'all' } })
    expect(parseHash('#/watch')).toEqual({ name: 'watch' })
    expect(parseHash('#/papers')).toEqual({ name: 'papers' })
    expect(parseHash('#/sources')).toEqual({ name: 'sources' })
    expect(parseHash('#/profile')).toEqual({ name: 'profile' })
    expect(parseHash('#/settings')).toEqual({ name: 'settings' })
  })

  it('shows Today for an empty hash or an in-page anchor, and "not found" for an address that names no page', () => {
    expect(parseHash('')).toEqual({ name: 'today' })
    expect(parseHash('#/')).toEqual({ name: 'today' })
    expect(parseHash('#r-main-content')).toEqual({ name: 'today' })
    expect(parseHash('#/nowhere')).toEqual({ name: 'notfound' })
    expect(parseHash('#/item/abc')).toEqual({ name: 'notfound' })
    expect(parseHash('#/item/-3')).toEqual({ name: 'notfound' })
    expect(parseHash('#/today/yesterday')).toEqual({ name: 'notfound' })
  })

  it('drops the sample-mode flag from feed filters', () => {
    expect(parseHash('#/feed?mock=1&saved=true')).toEqual({ name: 'feed', params: { saved: 'true' } })
  })
})

describe('buildHash', () => {
  it('round-trips through parseHash', () => {
    const routes: Route[] = [
      { name: 'today' },
      { name: 'today', day: '2026-11-10' },
      { name: 'item', id: 7 },
      { name: 'feed', params: {} },
      { name: 'feed', params: { kind: 'paper', q: 'surgical video' } },
      { name: 'settings' },
    ]
    for (const route of routes) expect(parseHash(buildHash(route))).toEqual(route)
  })

  it('omits empty feed parameters', () => {
    expect(buildHash({ name: 'feed', params: { section: '' } })).toBe('#/feed')
  })
})

describe('navigation', () => {
  it('pushes entries and goes back within the app', async () => {
    navigate({ name: 'feed', params: {} })
    navigate({ name: 'item', id: 3 })
    expect(window.location.hash).toBe('#/item/3')
    const popped = new Promise((resolve) => window.addEventListener('popstate', resolve, { once: true }))
    goBack()
    await popped
    expect(window.location.hash).toBe('#/feed')
  })

  it('goes to the fallback when the reader was opened directly', () => {
    window.history.replaceState(null, '', '/#/item/9')
    goBack()
    expect(window.location.hash).toBe('#/today')
  })

  it('announces replace navigation with a hashchange event', () => {
    let fired = 0
    const listener = () => (fired += 1)
    window.addEventListener('hashchange', listener)
    navigate({ name: 'feed', params: { saved: 'true' } }, { replace: true })
    window.removeEventListener('hashchange', listener)
    expect(fired).toBe(1)
    expect(window.location.hash).toBe('#/feed?saved=true')
  })
})

describe('scroll memory', () => {
  it('remembers offsets per route key and defaults to zero', () => {
    saveScroll('#/today', 640.4)
    saveScroll('#/feed', -20)
    expect(getScroll('#/today')).toBe(640)
    expect(getScroll('#/feed')).toBe(0)
    expect(getScroll('#/watch')).toBe(0)
  })

  it('restores the offset on the scroll container', () => {
    const element = document.createElement('div')
    element.appendChild(document.createElement('div'))
    const cancel = restoreScroll(element, 300)
    expect(element.scrollTop).toBe(300)
    cancel()
  })

  it('does nothing harmful for a zero offset', () => {
    const element = document.createElement('div')
    const cancel = restoreScroll(element, 0)
    expect(element.scrollTop).toBe(0)
    expect(() => cancel()).not.toThrow()
  })
})

describe('how a page was reached', () => {
  it('counts a Back/Forward step, and nothing else, as a return that may restore scroll', () => {
    navigate({ name: 'watch' })
    expect(arrivedByHistoryStep()).toBe(false)
    window.dispatchEvent(new PopStateEvent('popstate', { state: { radarIndex: 1 } }))
    expect(arrivedByHistoryStep()).toBe(true)
    navigate({ name: 'sources' })
    expect(arrivedByHistoryStep()).toBe(false)
    // A plain #fragment click fires popstate without the state this router stores.
    window.dispatchEvent(new PopStateEvent('popstate', { state: null }))
    expect(arrivedByHistoryStep()).toBe(false)
  })
})

