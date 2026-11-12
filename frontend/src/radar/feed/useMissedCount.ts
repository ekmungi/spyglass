// useMissedCount: how many items the Missed filter would list, for the number on its chip. It asks
// for one row only (the total is what counts) and asks again each time the Feed is shown, so the
// number follows what the reader opened in between.
import { useEffect, useState } from 'react'
import { getFeed } from '../api/client'

// The last number read, so a Feed opened again starts with the number already on its chip instead of
// the chip widening (and the controls after it shifting) when the answer arrives.
let lastKnown = 0

/** Forget the last number read (tests). */
export function clearMissedCount(): void {
  lastKnown = 0
}

/** The number of missed items (the last known one until the answer arrives). `active` false pauses the request. */
export function useMissedCount(active: boolean): number {
  const [count, setCount] = useState(lastKnown)
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    getFeed({ missed: true, limit: 1 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return
        lastKnown = page.total
        setCount(page.total)
      })
      .catch(() => {
        // The number is a hint on a chip: when it cannot be fetched the last known number stays,
        // and the Missed view itself shows its own error if it cannot load.
      })
    return () => controller.abort()
  }, [active])
  return count
}
