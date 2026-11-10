// One item's background jobs and note, read from the service and polled while a job
// runs. Like the full-text job, the state lives on the server, so it survives the reader being
// rebuilt when another item is opened.
import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import { isActive } from './jobs'
import type { CardJobs, JobKind } from './types'

export const JOBS_POLL_MS = 3000

export interface CardJobsState {
  data: CardJobs | null
  // The service's reason when starting or deleting was refused.
  error: string | null
  start: (kind: JobKind) => void
  cancel: () => void
  deleteNote: () => void
}

/**
 * @param cardId The item; the reader remounts per item, so this is stable for one hook.
 * @param onChanged Called after a job finishes or the note is deleted, so the caller can
 *                  reload the item (its note path and feedback change).
 */
export function useCardJobs(cardId: number, onChanged?: () => void): CardJobsState {
  const [data, setData] = useState<CardJobs | null>(null)
  const [error, setError] = useState<string | null>(null)
  const changedRef = useRef(onChanged)
  useEffect(() => {
    changedRef.current = onChanged
  }, [onChanged])

  // Whether the last read showed a job in progress: its end is what triggers onChanged.
  const wasActive = useRef(false)

  const load = useCallback(() => {
    return api
      .getCardJobs(cardId)
      .then((next) => {
        const now = isActive(next.jobs[0])
        if (wasActive.current && !now) changedRef.current?.()
        wasActive.current = now
        setData(next)
        return next
      })
      .catch(() => null)
  }, [cardId])

  useEffect(() => {
    load()
  }, [load])

  const active = isActive(data?.jobs[0])
  useEffect(() => {
    if (!active) return
    const timer = setInterval(load, JOBS_POLL_MS)
    return () => clearInterval(timer)
  }, [active, load])

  const start = (kind: JobKind) => {
    setError(null)
    api
      .startJob(kind, cardId)
      .then(() => load())
      .catch((err: unknown) => setError(err instanceof api.ApiError ? err.detail : 'Spyglass did not answer.'))
  }

  const cancel = () => {
    const job = data?.jobs[0]
    if (job && isActive(job)) api.cancelJob(job.id).then(() => load()).catch(() => {})
  }

  const deleteNote = () => {
    setError(null)
    api
      .deleteDetailNote(cardId)
      .then(() => load())
      .then(() => changedRef.current?.())
      .catch((err: unknown) => setError(err instanceof api.ApiError ? err.detail : 'Spyglass did not answer.'))
  }

  return { data, error, start, cancel, deleteNote }
}
