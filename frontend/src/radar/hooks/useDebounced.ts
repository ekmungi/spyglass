// useDebounced: a copy of a value that only updates after it has stopped changing for `ms`.
import { useEffect, useState } from 'react'

/** Return `value`, delayed until it has been stable for `ms` milliseconds. */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}
