// useResource: load data for a key with loading / error / reload. The last answer per key is kept
// in a module cache, so entering a page shows it at once while a fresh copy is fetched quietly
// and swapped in only when it differs (no flicker, no layout jump).
import { useCallback, useEffect, useRef, useState } from 'react'

const cache = new Map<string, unknown>()

/** How long an answer counts as fresh when the window regains focus (milliseconds). */
export const STALE_AFTER_MS = 30_000

export interface Resource<T> {
  data: T | undefined
  error: unknown
  /** True only while there is nothing to show yet (no cached answer). */
  loading: boolean
  /** True while a background refresh is in flight, whether or not a cached answer is on screen. */
  refreshing: boolean
  reload: () => void
  setData: (updater: (current: T | undefined) => T | undefined) => void
}

export interface ResourceOptions {
  /**
   * False while the page is hidden under another layer (the reader). Becoming true again fetches a
   * fresh copy, so coming back to a page never shows an answer from before you left. Default true.
   */
  active?: boolean
  /** Also refresh when the window regains focus after the answer is older than STALE_AFTER_MS. */
  revalidateOnFocus?: boolean
}

interface State<T> {
  key: string | null
  data: T | undefined
  error: unknown
  loading: boolean
  refreshing: boolean
}

/** Drop cached results (all, or one key). */
export function clearResourceCache(key?: string): void {
  if (key === undefined) cache.clear()
  else cache.delete(key)
}

/** The state for a key at first sight: the cached answer when there is one. */
function initial<T>(key: string | null): State<T> {
  const cached = key ? (cache.get(key) as T | undefined) : undefined
  return { key, data: cached, error: null, loading: key !== null && cached === undefined, refreshing: key !== null }
}

/** Structural equality for JSON answers, so an unchanged reply never replaces what is on screen. */
function sameAnswer(a: unknown, b: unknown): boolean {
  if (a === b) return true
  try {
    return JSON.stringify(a) === JSON.stringify(b)
  } catch {
    return false
  }
}

/**
 * Load `loader(signal)` whenever `key` changes; a null key skips loading. A cached value for the
 * key is shown immediately and refreshed in the background; errors keep the cached value.
 */
export function useResource<T>(key: string | null, loader: (signal: AbortSignal) => Promise<T>, options: ResourceOptions = {}): Resource<T> {
  const { active = true, revalidateOnFocus = false } = options
  const [state, setState] = useState<State<T>>(() => initial<T>(key))
  const [round, setRound] = useState(0)
  const loaderRef = useRef(loader)
  const startedAt = useRef(0)

  useEffect(() => {
    loaderRef.current = loader
  })

  // A new key starts from that key's cached answer. React re-renders at once; this render already
  // reports the new key's state, so one render never shows the previous key's data.
  let current = state
  if (state.key !== key) {
    current = initial<T>(key)
    setState(current)
  }

  useEffect(() => {
    if (key === null || !active) return
    const controller = new AbortController()
    startedAt.current = Date.now()
    loaderRef.current(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return
        cache.set(key, value)
        setState((previous) =>
          previous.key !== key
            ? previous
            : { key, data: sameAnswer(previous.data, value) ? previous.data : value, error: null, loading: false, refreshing: false },
        )
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return
        setState((previous) => (previous.key !== key ? previous : { ...previous, error: cause, loading: false, refreshing: false }))
      },
    )
    return () => controller.abort()
  }, [key, round, active])

  useEffect(() => {
    if (!revalidateOnFocus || !active || key === null) return
    const check = () => {
      if (document.visibilityState === 'hidden' || Date.now() - startedAt.current < STALE_AFTER_MS) return
      setState((previous) => ({ ...previous, refreshing: true }))
      setRound((value) => value + 1)
    }
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => {
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
  }, [revalidateOnFocus, active, key])

  const reload = useCallback(() => {
    setState((previous) => ({ ...previous, error: null, loading: previous.data === undefined, refreshing: true }))
    setRound((value) => value + 1)
  }, [])

  const setData = useCallback((updater: (current: T | undefined) => T | undefined) => {
    setState((previous) => {
      const next = updater(previous.data)
      if (previous.key) {
        if (next === undefined) cache.delete(previous.key)
        else cache.set(previous.key, next)
      }
      return { ...previous, data: next }
    })
  }, [])

  return { data: current.data, error: current.error, loading: current.loading, refreshing: current.refreshing, reload, setData }
}
