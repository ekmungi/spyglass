// useLoad: load one resource when a page opens, keep the old data on screen while it reloads
// (so nothing jumps), and expose a plain-language error with a reload function. With a cache key,
// the last answer is shown at once on the next visit and the page refetches quietly, replacing
// what is on screen only when the answer differs.
import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../../api/errors'

export interface LoadState<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** Fetch again; the current data stays visible until the new data arrives. */
  reload: () => void
  /** Replace the data locally, for example after a save the server has already confirmed. */
  replace: (next: T) => void
}

const answers = new Map<string, unknown>()

/** Forget the remembered answers (tests). */
export function clearLoadCache(): void {
  answers.clear()
}

/** Structural equality for JSON answers. */
function sameAnswer(a: unknown, b: unknown): boolean {
  try {
    return a === b || JSON.stringify(a) === JSON.stringify(b)
  } catch {
    return false
  }
}

interface Snapshot<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/**
 * Run `fetcher` on mount and on `reload()`; a cancelled or superseded request never updates the page.
 * `cacheKey` (optional) remembers the answer between visits so the page can show it before the fetch ends.
 */
export function useLoad<T>(fetcher: (signal: AbortSignal) => Promise<T>, cacheKey?: string): LoadState<T> {
  const [snapshot, setSnapshot] = useState<Snapshot<T>>(() => {
    const cached = cacheKey ? (answers.get(cacheKey) as T | undefined) : undefined
    return { data: cached ?? null, error: null, loading: cached === undefined }
  })
  const [round, setRound] = useState(0)
  const fetcherRef = useRef(fetcher)

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    const controller = new AbortController()
    fetcherRef.current(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return
        if (cacheKey) answers.set(cacheKey, data)
        // An unchanged answer keeps the data object on screen as it is: no re-render, no jump.
        setSnapshot((previous) => {
          if (previous.data !== null && sameAnswer(previous.data, data)) {
            return previous.error === null && !previous.loading ? previous : { data: previous.data, error: null, loading: false }
          }
          return { data, error: null, loading: false }
        })
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return
        setSnapshot((previous) => ({ data: previous.data, error: errorMessage(cause), loading: false }))
      },
    )
    return () => controller.abort()
    // cacheKey is fixed for the life of a page; round forces a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [round])

  const reload = useCallback(() => {
    setSnapshot((previous) => ({ ...previous, error: null, loading: true }))
    setRound((value) => value + 1)
  }, [])

  const replace = useCallback(
    (next: T) => {
      if (cacheKey) answers.set(cacheKey, next)
      setSnapshot({ data: next, error: null, loading: false })
    },
    [cacheKey],
  )

  return { ...snapshot, reload, replace }
}
