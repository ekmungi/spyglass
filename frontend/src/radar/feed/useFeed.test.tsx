// Tests for the Feed list hook: a refresh folds the fresh first page into the list on screen
// without shortening it, and an unchanged answer changes nothing.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import type { FeedPage, RadarItem } from '../api/types'
import { clearFeedCache, MISSED_PAGE_SIZE, PAGE_SIZE, pageSize, refreshHead, useFeed, type FeedState } from './useFeed'

function item(id: number, title = `Item ${id}`): RadarItem {
  return {
    id,
    title,
    headline: title,
    url: `https://example.org/${id}`,
    source: 'rss',
    origin: 'Wire',
    published_at: null,
    fetched_at: '2026-11-12T08:00:00',
    kind: 'news',
    section: '',
    section_label: '',
    tier: 'notable',
    score: null,
    why: null,
    key_points: [],
    entities: [],
    signal: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    has_reader: false,
  }
}

const state = (ids: number[], next: string | null = null, total = ids.length): FeedState => ({ items: ids.map((id) => item(id)), next, total })

beforeEach(() => clearFeedCache())
afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

describe('refreshHead', () => {
  it('returns the cached object itself when nothing changed', () => {
    const cached = state([1, 2, 3], 'c1')
    expect(refreshHead(cached, state([1, 2, 3], 'c1'))).toBe(cached)
  })

  it('puts new items on top and keeps the older pages already scrolled', () => {
    const cached = state([3, 2, 1, 0, -1], 'cursor-late', 5)
    const merged = refreshHead(cached, { items: [item(5), item(4), item(3), item(2)], next: 'cursor-early', total: 6 })
    expect(merged.items.map((entry) => entry.id)).toEqual([5, 4, 3, 2, 1, 0, -1])
    expect(merged.next).toBe('cursor-late')
    expect(merged.total).toBe(6)
  })

  it('keeps items that slid out of the first page when new ones arrived', () => {
    // The fresh page of 3 pushed item 1 off the end; it must not vanish from the list.
    const cached = state([3, 2, 1], 'c', 3)
    const merged = refreshHead(cached, { items: [item(5), item(4), item(3)], next: 'c2', total: 5 })
    expect(merged.items.map((entry) => entry.id)).toEqual([5, 4, 3, 2, 1])
  })

  it('replaces the list when the fresh page shares nothing with it', () => {
    const merged = refreshHead(state([1, 2], 'old'), { items: [item(8), item(9)], next: 'new', total: 2 })
    expect(merged.items.map((entry) => entry.id)).toEqual([8, 9])
    expect(merged.next).toBe('new')
  })

  it('takes a first page with nothing after it as the whole list, dropping what is no longer there', () => {
    const cached = state([1, 2, 3])
    expect(refreshHead(cached, state([1, 2])).items.map((entry) => entry.id)).toEqual([1, 2])
    // An unchanged whole list still comes back as the same object.
    expect(refreshHead(cached, state([1, 2, 3]))).toBe(cached)
  })

  it('shows a changed item in place', () => {
    const cached = state([1, 2])
    const merged = refreshHead(cached, { items: [item(1, 'Edited'), item(2)], next: null, total: 2 })
    expect(merged).not.toBe(cached)
    expect(merged.items[0].headline).toBe('Edited')
  })
})

describe('useFeed', () => {
  function serve(pages: () => FeedPage): number[] {
    const calls: number[] = []
    setFetchForTesting(async () => {
      calls.push(Date.now())
      return new Response(JSON.stringify(pages()), { status: 200 })
    })
    return calls
  }

  it('shows the cached list at once on the next visit and picks up new items quietly', async () => {
    let answer: FeedPage = { items: [item(2), item(1)], next_before: null, total: 2 }
    serve(() => answer)
    const first = renderHook(() => useFeed({}))
    await waitFor(() => expect(first.result.current.items).toHaveLength(2))
    first.unmount()

    answer = { items: [item(3), item(2), item(1)], next_before: null, total: 3 }
    const second = renderHook(() => useFeed({}))
    expect(second.result.current.items.map((entry) => entry.id)).toEqual([2, 1]) // cached, no skeleton
    expect(second.result.current.loading).toBe(false)
    await waitFor(() => expect(second.result.current.items.map((entry) => entry.id)).toEqual([3, 2, 1]))
  })

  it('does not fetch while the page is hidden under the reader, and refetches when it is shown again', async () => {
    const calls = serve(() => ({ items: [item(1)], next_before: null, total: 1 }))
    const view = renderHook(({ active }) => useFeed({}, { active }), { initialProps: { active: true } })
    await waitFor(() => expect(view.result.current.items).toHaveLength(1))
    expect(calls).toHaveLength(1)
    view.rerender({ active: false })
    await act(async () => undefined)
    expect(calls).toHaveLength(1)
    view.rerender({ active: true })
    await waitFor(() => expect(calls).toHaveLength(2))
  })

  it('with holdOnReturn, keeps the list as it was when the page is shown again, but a reload still fetches', async () => {
    const calls = serve(() => ({ items: [item(1)], next_before: null, total: 1 }))
    const view = renderHook(({ active }) => useFeed({ missed: true }, { active, holdOnReturn: true }), { initialProps: { active: true } })
    await waitFor(() => expect(view.result.current.items).toHaveLength(1))
    view.rerender({ active: false })
    view.rerender({ active: true })
    await act(async () => undefined)
    expect(calls).toHaveLength(1)
    act(() => view.result.current.reload())
    await waitFor(() => expect(calls).toHaveLength(2))
  })

  it('with holdOnReturn, still loads when the page was hidden before the first answer arrived', async () => {
    const calls = serve(() => ({ items: [item(1)], next_before: null, total: 1 }))
    const view = renderHook(({ active }) => useFeed({ missed: true }, { active, holdOnReturn: true }), { initialProps: { active: true } })
    view.rerender({ active: false }) // aborts the first request
    view.rerender({ active: true })
    await waitFor(() => expect(view.result.current.items).toHaveLength(1))
    expect(calls.length).toBeGreaterThanOrEqual(1)
  })

  it('asks for the largest page under Missed, which has no cursor, and the usual page otherwise', async () => {
    expect(pageSize({})).toBe(PAGE_SIZE)
    expect(pageSize({ missed: true })).toBe(MISSED_PAGE_SIZE)
    const urls: string[] = []
    setFetchForTesting(async (input) => {
      urls.push(String(input))
      return new Response(JSON.stringify({ items: [item(1)], next_before: null, total: 1 }), { status: 200 })
    })
    const view = renderHook(() => useFeed({ missed: true }))
    await waitFor(() => expect(view.result.current.items).toHaveLength(1))
    expect(urls[0]).toContain('missed=true')
    expect(urls[0]).toContain(`limit=${MISSED_PAGE_SIZE}`)
  })
})
