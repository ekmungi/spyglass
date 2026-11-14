// useAfterDelay: true once `delayMs` has passed since the component mounted, so a view can hold back
// a message that would only flash by when the wait turns out to be short.
import { useEffect, useState } from 'react'

/**
 * Return false until `delayMs` milliseconds after mount, then true. A delay of zero or less is true
 * at once. The timer is cleared when the component unmounts, for example when the awaited answer arrives.
 */
export function useAfterDelay(delayMs: number): boolean {
  const [passed, setPassed] = useState(delayMs <= 0)
  useEffect(() => {
    if (delayMs <= 0) return
    const timer = setTimeout(() => setPassed(true), delayMs)
    return () => clearTimeout(timer)
  }, [delayMs])
  return passed
}
