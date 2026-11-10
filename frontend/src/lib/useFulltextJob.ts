// One card's stored full text plus the background fetch job driving it.
// The job state is READ FROM THE SERVER on every mount rather than held in component
// state, which is what makes a fetch survive the reader pane being destroyed when another
// card is opened.
import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import { isJobActive } from './fetchJob'
import { toState, type ReaderState } from './readerState'
import type { CardData } from './types'

// How often to re-read a card's full text while its job is still in flight. The slow rung
// of the acquisition ladder (a real Chromium) runs 30-60s, so 2s is responsive without
// being chatty, and polling stops the moment the job reaches a terminal state.
export const JOB_POLL_MS = 2000

export interface FulltextJob {
  /** What the reader body should render right now. */
  state: ReaderState
  /** Queue a fetch for this card; progress is then read back from the server. */
  fetchNow: () => void
}

/**
 * Track a card's full text and the server-side fetch job that produces it.
 *
 * @param cardId     Card whose full text to track. The reader remounts per card, so this
 *                   is stable for the life of a given hook instance; a change still
 *                   re-reads, and any in-flight response for the old card is discarded.
 * @param onComplete Called with the freshly re-read card when a job completes, so the
 *                   caller can merge the new summary/category in place. The POST no longer
 *                   returns an enrichment result — this is where that merge
 *                   moved to, and re-reading is what keeps it honest.
 * @returns The reader display state plus a `fetchNow` that enqueues a fetch.
 */
export function useFulltextJob(cardId: number, onComplete: (card: CardData) => void): FulltextJob {
  const [state, setState] = useState<ReaderState>({ phase: 'loading' })
  // Held in a ref so a caller passing a fresh closure each render cannot restart the poll.
  const completeRef = useRef(onComplete)
  useEffect(() => {
    completeRef.current = onComplete
  }, [onComplete])
  // Lifetime guards for the completion callback. They deliberately do NOT use the poll
  // effect's own cancellation flag: reaching a terminal state SETS STATE, which tears that
  // effect down, so by the time the follow-up card read resolves its flag is already
  // cancelled and the merge would be dropped. What actually disqualifies a merge is the
  // component being gone or having moved to another card, which is what these track.
  const mountedRef = useRef(true)
  useEffect(() => () => {
    mountedRef.current = false
  }, [])
  const cardIdRef = useRef(cardId)
  useEffect(() => {
    cardIdRef.current = cardId
  }, [cardId])

  // Initial read: this is the mount that has to discover a fetch it never saw start.
  useEffect(() => {
    let stale = false
    api
      .getFulltext(cardId)
      .then((result) => {
        if (!stale) setState(toState(result))
      })
      .catch(() => {
        if (!stale) setState({ phase: 'failed', status: 'error' })
      })
    return () => {
      stale = true
    }
  }, [cardId])

  // Poll only while a job is actually in flight. Depending on the boolean rather than the
  // whole state keeps the interval alive across polls that change nothing.
  const waiting = state.phase === 'fetching'
  useEffect(() => {
    if (!waiting) return
    let stale = false
    const timer = setInterval(() => {
      api
        .getFulltext(cardId)
        .then((result) => {
          // Still working: leave the state alone so this effect (and its timer) survives.
          if (stale || isJobActive(result.job)) return
          setState(toState(result))
          // Only a job that ran to completion can have changed the card. One that raised
          // stored nothing and enriched nothing, so re-reading buys a request and no news.
          if (result.job?.status !== 'done') return
          return api.getCard(cardId).then((full) => {
            if (mountedRef.current && cardIdRef.current === cardId) completeRef.current(full)
          })
        })
        .catch(() => {
          if (!stale) setState({ phase: 'failed', status: 'error' })
        })
    }, JOB_POLL_MS)
    return () => {
      stale = true
      clearInterval(timer)
    }
  }, [cardId, waiting])

  const fetchNow = useCallback(() => {
    // Optimistic: the POST only records the job, so showing progress immediately is
    // accurate. The poll above takes over from here and owns every later transition.
    setState({ phase: 'fetching' })
    api.fetchFulltext(cardId).catch(() => {
      // Nothing was queued, so nothing will ever complete — say so rather than spin.
      setState({ phase: 'failed', status: 'error' })
    })
  }, [cardId])

  return { state, fetchNow }
}
