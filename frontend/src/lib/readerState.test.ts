// Tests for the reader display state machine, in particular the structured
// fetch-failure reason (error, tier, type) that the reader surfaces.
import { describe, expect, it } from 'vitest'
import { toState } from './readerState'
import type { FulltextResult } from './types'

describe('toState', () => {
  it('maps a ready result (markdown present) to the ready phase', () => {
    const result: FulltextResult = { status: 'ok', markdown: 'Body text.' }
    expect(toState(result)).toEqual({ phase: 'ready', markdown: 'Body text.' })
  })

  it('maps an absent result to the absent phase', () => {
    const result: FulltextResult = { status: 'absent', markdown: null }
    expect(toState(result)).toEqual({ phase: 'absent' })
  })

  it('maps a failed result WITH a structured reason to failed carrying reason/tier/detectedType', () => {
    const result: FulltextResult = {
      status: 'failed',
      markdown: null,
      error: 'blocked at T0 (HTTP 403); T3 (browser) also failed: timeout',
      error_class: 'blocked',
      tier_reached: 'T3',
      detected_type: 'html',
      http_status: 403,
    }
    expect(toState(result)).toEqual({
      phase: 'failed',
      status: 'failed',
      reason: 'blocked at T0 (HTTP 403); T3 (browser) also failed: timeout',
      tier: 'T3',
      detectedType: 'html',
    })
  })

  it('maps a failed result WITHOUT a reason (older rows / null) to failed with reason undefined', () => {
    const result: FulltextResult = { status: 'failed', markdown: null }
    const state = toState(result)
    expect(state).toEqual({ phase: 'failed', status: 'failed', reason: undefined, tier: undefined, detectedType: undefined })
    if (state.phase === 'failed') {
      expect(state.reason).toBeUndefined()
    }
  })

  it('maps a failed result with error explicitly null to failed with reason undefined (falls back)', () => {
    const result: FulltextResult = {
      status: 'failed',
      markdown: null,
      error: null,
      error_class: null,
      tier_reached: null,
      detected_type: null,
      http_status: null,
    }
    const state = toState(result)
    expect(state.phase).toBe('failed')
    if (state.phase === 'failed') {
      expect(state.reason).toBeFalsy()
    }
  })

  it('maps a paywalled status to failed, preserving the status string', () => {
    const result: FulltextResult = { status: 'paywalled', markdown: null }
    const state = toState(result)
    expect(state).toEqual({ phase: 'failed', status: 'paywalled', reason: undefined, tier: undefined, detectedType: undefined })
  })

  // The job rides along on the GET so a freshly-mounted reader renders progress
  // it never witnessed being started.
  it('maps a queued job to fetching even though nothing is stored yet', () => {
    const result: FulltextResult = {
      status: 'absent',
      markdown: null,
      job: { job_id: 3, card_id: 7, status: 'queued', error: null },
    }
    expect(toState(result)).toEqual({ phase: 'fetching' })
  })

  it('maps a running job to fetching', () => {
    const result: FulltextResult = {
      status: 'absent',
      markdown: null,
      job: { job_id: 3, card_id: 7, status: 'running', error: null },
    }
    expect(toState(result)).toEqual({ phase: 'fetching' })
  })

  it('lets an in-flight re-fetch outrank already-stored markdown', () => {
    // Re-fetching a card that already has text must show progress, matching what the
    // in-session fetch has always done rather than looking like nothing happened.
    const result: FulltextResult = {
      status: 'ok',
      markdown: 'Old body text.',
      job: { job_id: 4, card_id: 7, status: 'running', error: null },
    }
    expect(toState(result)).toEqual({ phase: 'fetching' })
  })

  it('ignores a terminal job and reports the stored result', () => {
    const result: FulltextResult = {
      status: 'ok',
      markdown: 'Body text.',
      job: { job_id: 5, card_id: 7, status: 'done', error: null },
    }
    expect(toState(result)).toEqual({ phase: 'ready', markdown: 'Body text.' })
  })

  it('surfaces a failed job as the reason when the fetch stored nothing at all', () => {
    // A job that RAISED stores no fulltext row, so its own error is the only reason there
    // is to show -- notably `interrupted` after the service was killed mid-fetch.
    const result: FulltextResult = {
      status: 'absent',
      markdown: null,
      job: { job_id: 6, card_id: 7, status: 'failed', error: 'interrupted' },
    }
    expect(toState(result)).toEqual({ phase: 'failed', status: 'failed', reason: 'interrupted' })
  })

  it('still reports absent when the last job failed without recording a reason', () => {
    const result: FulltextResult = {
      status: 'absent',
      markdown: null,
      job: { job_id: 7, card_id: 7, status: 'failed', error: null },
    }
    expect(toState(result)).toEqual({ phase: 'failed', status: 'failed', reason: undefined })
  })

  it('maps an absent result with no job history to the absent phase', () => {
    const result: FulltextResult = { status: 'absent', markdown: null, job: null }
    expect(toState(result)).toEqual({ phase: 'absent' })
  })
})
