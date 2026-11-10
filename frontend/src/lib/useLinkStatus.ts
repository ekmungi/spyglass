// Keeps the linked-session status current: read on open, every 20 s, when the window
// comes back into view, and every 4 s for two minutes after a new linked session is opened,
// until that session links (the user presses Enter in Claude desktop first). A failed read keeps
// the last known status: a brief hiccup must not look like "no session linked", or the next
// conversation would open a new session and cut off the working one. A closing window tells the
// service, which ends the link when no Spyglass window checks in again soon after.
import { useCallback, useEffect, useState } from 'react'
import * as api from './api'
import type { LinkStatus } from './types'

const SLOW_MS = 20000
const FAST_MS = 4000
const WATCH_MS = 2 * 60 * 1000

interface Watch {
  until: number
  // The link that existed when the new session was opened; a different one means it linked.
  from: string | null
}

export function useLinkStatus(): {
  status: LinkStatus | null
  watch: () => void
  refresh: () => Promise<LinkStatus | null>
} {
  const [status, setStatus] = useState<LinkStatus | null>(null)
  const [watching, setWatching] = useState<Watch | null>(null)

  const refresh = useCallback(
    () =>
      api
        .getLinkStatus()
        .then((next) => {
          setStatus(next)
          return next
        })
        .catch(() => null),
    [],
  )

  useEffect(() => {
    void refresh()
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    const onClosing = () => api.sayWindowClosing()
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('pagehide', onClosing)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('pagehide', onClosing)
    }
  }, [refresh])

  const fast = watching !== null && (status?.linked_at ?? null) === watching.from
  useEffect(() => {
    const timer = setInterval(
      () => {
        if (watching && Date.now() > watching.until) setWatching(null)
        void refresh()
      },
      fast ? FAST_MS : SLOW_MS,
    )
    return () => clearInterval(timer)
  }, [fast, watching, refresh])

  const watch = useCallback(() => {
    setWatching({ until: Date.now() + WATCH_MS, from: status?.linked_at ?? null })
    void refresh()
  }, [status, refresh])

  return { status, watch, refresh }
}
