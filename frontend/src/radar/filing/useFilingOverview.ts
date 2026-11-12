// useFilingOverview: GET /filing for the To file view (the queue plus the background run's status,
// open questions, plan and recent filings), loaded while the view is on and again whenever the
// queue changes or the view asks for it. An older service without background filing gives empty
// groups; any other failure keeps what was shown and reports the error.
import { useCallback, useEffect, useState } from 'react'
import { getFilingOverview } from '../api/client'
import { errorMessage, isMissing } from '../api/errors'
import type { FilingOverview } from '../api/types'
import { noteFilingOverview } from '../state/filingConfigured'
import { useFilingVersion } from '../state/filingState'

export interface FilingOverviewState {
  data: FilingOverview | null
  error: string | null
  reload: () => void
}

/** Load the overview while `enabled`. */
export function useFilingOverview(enabled: boolean): FilingOverviewState {
  const [data, setData] = useState<FilingOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [round, setRound] = useState(0)
  const queueVersion = useFilingVersion()

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    getFilingOverview(controller.signal)
      .then((overview) => {
        if (controller.signal.aborted) return
        setData(overview)
        noteFilingOverview(overview)
        setError(null)
      })
      .catch((cause) => {
        if (controller.signal.aborted) return
        setError(isMissing(cause) ? null : errorMessage(cause))
      })
    return () => controller.abort()
  }, [enabled, round, queueVersion])

  const reload = useCallback(() => setRound((value) => value + 1), [])
  return { data, error, reload }
}
