// usePresence: keep an overlay mounted while it plays its exit, then let it go. The element gets
// data-state="open|closed" from `state`; its stylesheet animates the closed state.
import { useEffect, useState } from 'react'
import { motionMs, type DurationToken } from './motion'

export type PresenceState = 'open' | 'closed'

export interface Presence {
  /** Render the element while this is true. */
  mounted: boolean
  /** Put on the element as data-state; "closed" while the exit plays. */
  state: PresenceState
}

/**
 * Follow `open`, but on closing stay mounted for the exit duration named by `exitToken` (read
 * from tokens.css, so it is 0 under reduced motion or when styles are absent, and then the element
 * unmounts in the same render). Reopening during the exit cancels the unmount.
 */
export function usePresence(open: boolean, exitToken: DurationToken): Presence {
  const [exitMs, setExitMs] = useState(0)
  const [previousOpen, setPreviousOpen] = useState(open)

  // Adjust state while rendering when `open` changes, as React recommends for derived values:
  // a close starts an exit only when there is an exit to play.
  if (open !== previousOpen) {
    setPreviousOpen(open)
    setExitMs(open ? 0 : motionMs(exitToken))
  }

  useEffect(() => {
    if (exitMs === 0) return
    const timer = window.setTimeout(() => setExitMs(0), exitMs)
    return () => window.clearTimeout(timer)
  }, [exitMs])

  return { mounted: open || exitMs > 0, state: open ? 'open' : 'closed' }
}
