// useElapsed: whole seconds since `active` became true, for honest "still working" messages.
import { useEffect, useState } from 'react'

/** Counts seconds while `active` is true and returns to 0 when it turns false. */
export function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!active) return
    const start = Date.now()
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - start) / 1000)), 1000)
    return () => {
      clearInterval(timer)
      setSeconds(0)
    }
  }, [active])
  return seconds
}
