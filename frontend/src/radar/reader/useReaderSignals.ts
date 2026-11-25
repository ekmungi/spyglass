// useReaderSignals: records "open" once per reader visit, once the item has loaded and is drawn, and
// "dwell" every 30 s while the tab is visible after that. Signals are best-effort learning data, so a
// failed send is dropped without a message.
import { useEffect } from 'react'
import { sendSignal } from '../api/client'

export const DWELL_SECONDS = 30

/** Send a signal and ignore failure: the reader must never see an error for background telemetry. */
function fire(id: number, kind: string, value: string | null): void {
  sendSignal(id, { kind, value }).catch(() => undefined)
}

/**
 * Record the open and the dwell time for item `id` while the reader shows it. `loaded` is false until
 * the item has arrived: a story stepped past while it still loads was never drawn, so it sends nothing.
 */
export function useReaderSignals(id: number, loaded: boolean): void {
  useEffect(() => {
    if (!loaded) return
    fire(id, 'open', null)
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') fire(id, 'dwell', String(DWELL_SECONDS))
    }, DWELL_SECONDS * 1000)
    return () => clearInterval(timer)
  }, [id, loaded])
}
