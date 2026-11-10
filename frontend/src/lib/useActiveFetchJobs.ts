// Dashboard-wide poller for cards with a fetch in flight, driving the
// list-row pending markers. Deliberately its own endpoint rather than a field on
// /api/cards, whose payload is kept lean.
import { useCallback, useEffect, useState } from 'react'
import * as api from './api'

// Matches the reader's poll cadence. The loop runs ONLY while something is in flight, so
// an idle dashboard sits on no timer at all.
export const ACTIVE_JOBS_POLL_MS = 2000

export interface ActiveFetchJobs {
  /** Card ids with a queued or running fetch. */
  fetchingIds: Set<number>
  /** Re-check immediately — how the reader says "I just queued one". */
  refresh: () => void
}

/** Whether a freshly polled id list differs from the set already held. */
function changed(current: Set<number>, ids: number[]): boolean {
  return current.size !== ids.length || ids.some((id) => !current.has(id))
}

/**
 * Poll the set of cards with a fetch in flight, only while there is one.
 *
 * Reading this once on mount is what makes a mid-fetch dashboard reload still show its
 * markers; the loop then continues until the queue drains and stops on its own.
 *
 * @returns The in-flight card ids and a `refresh` that restarts the loop on demand.
 */
export function useActiveFetchJobs(): ActiveFetchJobs {
  const [fetchingIds, setFetchingIds] = useState<Set<number>>(() => new Set())
  // Bumped by refresh(); re-running the effect is what restarts a loop that went idle.
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let stale = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = () => {
      api
        .getActiveFetchJobs()
        .then((ids) => {
          if (stale) return
          // Returning the SAME set when nothing moved makes React skip the render entirely;
          // WorkspaceView re-filters the whole corpus on every one of them.
          setFetchingIds((current) => (changed(current, ids) ? new Set(ids) : current))
          if (ids.length > 0) timer = setTimeout(poll, ACTIVE_JOBS_POLL_MS)
        })
        .catch(() => {
          // A markers-only nicety: a failed poll ends the loop rather than retrying
          // forever against a service that may be down.
        })
    }
    poll()
    return () => {
      stale = true
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  return { fetchingIds, refresh }
}
