// A debounced wrapper around a callback: coalesces rapid calls into one trailing invocation after
// `delay` ms of quiet. Collapses a burst of thumbs into a single background reload.
import { useCallback, useEffect, useRef } from 'react'

/** Returns a stable function that calls `fn` once, `delay` ms after the last invocation. The latest
 * `fn` is always used, and the pending timer is cleared on unmount. */
export function useDebouncedCallback(fn: () => void, delay: number): () => void {
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  }, [fn])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )
  return useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => fnRef.current(), delay)
  }, [delay])
}
