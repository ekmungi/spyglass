// Reader display state machine: maps fulltext responses to render phases.
import { isJobActive } from './fetchJob'
import type { FulltextResult } from './types'

export type ReaderState =
  | { phase: 'loading' | 'fetching' }
  | { phase: 'ready'; markdown: string }
  | { phase: 'absent' }
  | {
      phase: 'failed'
      status: string
      // Structured failure reason; undefined on older rows
      // or non-failed statuses, so the reader falls back to the generic message.
      reason?: string | null
      tier?: string | null
      detectedType?: string | null
    }

/** Map a fulltext response onto the reader's display state.
 *
 * The response's job is consulted first: a queued or running fetch outranks
 * whatever is stored, which is what lets a freshly-mounted pane render progress it never
 * witnessed being started.
 */
export function toState(result: FulltextResult): ReaderState {
  if (isJobActive(result.job)) {
    return { phase: 'fetching' }
  }
  if (result.markdown) {
    return { phase: 'ready', markdown: result.markdown }
  }
  if (result.status === 'absent') {
    // A job that RAISED stores no fulltext row at all, so its own error is the only reason
    // there is to show -- notably `interrupted` after the service was killed mid-fetch.
    // Without this, an interrupted fetch reads as "never fetched".
    if (result.job?.status === 'failed') {
      return { phase: 'failed', status: 'failed', reason: result.job.error ?? undefined }
    }
    return { phase: 'absent' }
  }
  return {
    phase: 'failed',
    status: result.status,
    reason: result.error ?? undefined,
    tier: result.tier_reached ?? undefined,
    detectedType: result.detected_type ?? undefined,
  }
}
