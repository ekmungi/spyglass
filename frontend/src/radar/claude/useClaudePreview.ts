// useClaudePreview: asks the service for exactly what would be sent to Claude Code, again (after a
// 300 ms pause) every time a choice changes. The last text stays on screen while the next one loads.
import { useEffect, useState } from 'react'
import { previewClaude } from '../api/client'
import { errorMessage, isMissing, NOT_AVAILABLE_YET } from '../api/errors'
import type { ClaudePreview, ClaudeRequest } from '../api/types'
import { useDebounced } from '../hooks/useDebounced'

/** How long a choice must stay unchanged before the preview is asked for again. */
export const PREVIEW_DEBOUNCE_MS = 300

export interface PreviewState {
  /** The latest text the service sent, kept while a newer one loads. */
  preview: ClaudePreview | null
  /** True while a change is waiting to be sent or the answer is on its way. */
  loading: boolean
  /** A plain sentence when the preview could not be made (or is not in this copy yet); else null. */
  problem: string | null
}

interface Result {
  key: string
  preview: ClaudePreview | null
  problem: string | null
}

/** The preview for `request` on item `itemId`. */
export function useClaudePreview(itemId: number, request: ClaudeRequest): PreviewState {
  const key = JSON.stringify([itemId, request])
  const settled = useDebounced(key, PREVIEW_DEBOUNCE_MS)
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const [id, body] = JSON.parse(settled) as [number, ClaudeRequest]
    previewClaude(id, body, controller.signal).then(
      (preview) => {
        if (!controller.signal.aborted) setResult({ key: settled, preview, problem: null })
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return
        setResult((previous) => ({ key: settled, preview: previous?.preview ?? null, problem: isMissing(cause) ? NOT_AVAILABLE_YET : errorMessage(cause) }))
      },
    )
    return () => controller.abort()
  }, [settled])

  return { preview: result?.preview ?? null, loading: result?.key !== key, problem: result?.key === key ? result.problem : null }
}
