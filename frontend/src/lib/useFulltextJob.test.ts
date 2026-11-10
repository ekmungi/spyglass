// Tests for the reader's full-text hook: job state comes from the SERVER on
// every mount, so a fetch survives the reader pane being destroyed on navigation.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import { makeCard } from '../test/fixtures'
import type { FetchJobState, FulltextResult } from './types'
import { JOB_POLL_MS, useFulltextJob } from './useFulltextJob'

const CARD_ID = 7

const job = (status: FetchJobState['status'], error: string | null = null): FetchJobState => ({
  job_id: 1,
  card_id: CARD_ID,
  status,
  error,
})

const absent = (j?: FetchJobState): FulltextResult => ({
  status: 'absent',
  markdown: null,
  job: j ?? null,
})

const stored = (markdown: string, j?: FetchJobState): FulltextResult => ({
  status: 'ok',
  markdown,
  job: j ?? null,
})

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

describe('useFulltextJob', () => {
  it('renders the stored markdown once the initial read resolves', async () => {
    vi.spyOn(api, 'getFulltext').mockResolvedValue(stored('Body text.'))
    const { result } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    expect(result.current.state).toEqual({ phase: 'loading' })
    await tick()
    expect(result.current.state).toEqual({ phase: 'ready', markdown: 'Body text.' })
  })

  it('shows fetching on mount when the server reports an in-flight job', async () => {
    // The core of the bug: this pane never saw the fetch start — it was rebuilt from
    // scratch when the user came back to the card. The state must come off the server.
    vi.spyOn(api, 'getFulltext').mockResolvedValue(absent(job('running')))
    const { result } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    expect(result.current.state).toEqual({ phase: 'fetching' })
  })

  it('polls while the job is in flight and renders the text once it completes', async () => {
    const getFulltext = vi
      .spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(stored('Fetched body.', job('done')))
    vi.spyOn(api, 'getCard').mockResolvedValue(makeCard({ id: CARD_ID }))
    const { result } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    expect(result.current.state).toEqual({ phase: 'fetching' })

    await tick(JOB_POLL_MS)
    expect(result.current.state).toEqual({ phase: 'fetching' })

    await tick(JOB_POLL_MS)
    expect(result.current.state).toEqual({ phase: 'ready', markdown: 'Fetched body.' })
    expect(getFulltext).toHaveBeenCalledTimes(3)
  })

  it('re-reads the card and hands it to onComplete when the job finishes', async () => {
    // The POST no longer returns a summary, so the in-place card merge has
    // to happen here, from a fresh getCard.
    vi.spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(stored('Fetched body.', job('done')))
    const fresh = makeCard({ id: CARD_ID, summary: 'Fresh AI summary.', category: 'AI' })
    vi.spyOn(api, 'getCard').mockResolvedValue(fresh)
    const onComplete = vi.fn()
    renderHook(() => useFulltextJob(CARD_ID, onComplete))
    await tick()
    await tick(JOB_POLL_MS)
    expect(api.getCard).toHaveBeenCalledWith(CARD_ID)
    expect(onComplete).toHaveBeenCalledWith(fresh)
  })

  it('stops polling once the job reaches a terminal state', async () => {
    const getFulltext = vi
      .spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(stored('Fetched body.', job('done')))
    vi.spyOn(api, 'getCard').mockResolvedValue(makeCard({ id: CARD_ID }))
    renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    await tick(JOB_POLL_MS)
    expect(getFulltext).toHaveBeenCalledTimes(2)

    await tick(JOB_POLL_MS * 5)
    expect(getFulltext).toHaveBeenCalledTimes(2)
  })

  it('still merges when the card read resolves AFTER the poll effect is torn down', async () => {
    // Regression, caught only by a live run against the real service.
    // Reaching a terminal state calls setState, which tears down the very effect the poll
    // callback is running inside. Gating the follow-up merge on that effect's own
    // cancellation flag therefore drops it every time in the browser — and the earlier tests
    // hid this because act() defers React's teardown until the act scope exits, letting an
    // immediately-resolved getCard sneak in first. Delaying getCard reproduces real ordering.
    vi.spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(stored('Fetched body.', job('done')))
    const fresh = makeCard({ id: CARD_ID, summary: 'Fresh AI summary.' })
    vi.spyOn(api, 'getCard').mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(fresh), 50)),
    )
    const onComplete = vi.fn()
    renderHook(() => useFulltextJob(CARD_ID, onComplete))
    await tick()
    await tick(JOB_POLL_MS) // job goes terminal; the poll effect tears itself down here
    await tick(100) // ...and only now does the card read come back
    expect(onComplete).toHaveBeenCalledWith(fresh)
  })

  it('drops the merge when the pane unmounted before the card read came back', async () => {
    // The guard still has to mean something: a merge into a pane the user closed is a
    // setState on an unmounted component.
    vi.spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(stored('Fetched body.', job('done')))
    vi.spyOn(api, 'getCard').mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(makeCard({ id: CARD_ID })), 50)),
    )
    const onComplete = vi.fn()
    const { unmount } = renderHook(() => useFulltextJob(CARD_ID, onComplete))
    await tick()
    await tick(JOB_POLL_MS)
    unmount()
    await tick(100)
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('does not re-read the card when the job itself failed', async () => {
    // A raised job stored nothing and changed nothing; re-reading the card buys a request
    // and no new information.
    vi.spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(absent(job('running')))
      .mockResolvedValue(absent(job('failed', 'interrupted')))
    vi.spyOn(api, 'getCard').mockResolvedValue(makeCard({ id: CARD_ID }))
    const onComplete = vi.fn()
    const { result } = renderHook(() => useFulltextJob(CARD_ID, onComplete))
    await tick()
    await tick(JOB_POLL_MS)
    expect(result.current.state).toEqual({
      phase: 'failed',
      status: 'failed',
      reason: 'interrupted',
    })
    expect(api.getCard).not.toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('stops polling on unmount so a closed reader never keeps hitting the service', async () => {
    const getFulltext = vi.spyOn(api, 'getFulltext').mockResolvedValue(absent(job('running')))
    const { unmount } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    await tick(JOB_POLL_MS)
    const callsBeforeUnmount = getFulltext.mock.calls.length
    unmount()
    await tick(JOB_POLL_MS * 3)
    expect(getFulltext).toHaveBeenCalledTimes(callsBeforeUnmount)
  })

  it('fetchNow queues the job and switches straight to fetching', async () => {
    vi.spyOn(api, 'getFulltext').mockResolvedValue(absent())
    const fetchFulltext = vi.spyOn(api, 'fetchFulltext').mockResolvedValue(job('queued'))
    const { result } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    expect(result.current.state).toEqual({ phase: 'absent' })

    await act(async () => {
      result.current.fetchNow()
    })
    expect(fetchFulltext).toHaveBeenCalledWith(CARD_ID)
    expect(result.current.state).toEqual({ phase: 'fetching' })
  })

  it('surfaces a failure — and stops polling — when the enqueue itself fails', async () => {
    // Without this the pane would sit on "Fetching..." forever for a job that was never queued.
    vi.spyOn(api, 'getFulltext').mockResolvedValue(absent())
    vi.spyOn(api, 'fetchFulltext').mockRejectedValue(new Error('503'))
    const { result } = renderHook(() => useFulltextJob(CARD_ID, vi.fn()))
    await tick()
    await act(async () => {
      result.current.fetchNow()
    })
    await tick()
    expect(result.current.state).toEqual({ phase: 'failed', status: 'error' })
  })

  it('re-reads from the server when the hook switches to another card', async () => {
    const getFulltext = vi
      .spyOn(api, 'getFulltext')
      .mockResolvedValueOnce(stored('First body.'))
      .mockResolvedValue(stored('Second body.'))
    const { result, rerender } = renderHook(({ id }) => useFulltextJob(id, vi.fn()), {
      initialProps: { id: CARD_ID },
    })
    await tick()
    expect(result.current.state).toEqual({ phase: 'ready', markdown: 'First body.' })

    rerender({ id: 99 })
    await tick()
    expect(getFulltext).toHaveBeenLastCalledWith(99)
    expect(result.current.state).toEqual({ phase: 'ready', markdown: 'Second body.' })
  })
})
