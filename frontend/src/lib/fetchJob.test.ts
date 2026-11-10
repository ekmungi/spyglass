// Tests for the fetch-job status helpers that decide when the UI keeps waiting.
import { describe, expect, it } from 'vitest'
import { isJobActive } from './fetchJob'
import type { FetchJobState } from './types'

const job = (status: FetchJobState['status']): FetchJobState => ({
  job_id: 1,
  card_id: 7,
  status,
  error: null,
})

describe('isJobActive', () => {
  it('treats a queued job as active', () => {
    expect(isJobActive(job('queued'))).toBe(true)
  })

  it('treats a running job as active', () => {
    expect(isJobActive(job('running'))).toBe(true)
  })

  it('treats done and failed as terminal', () => {
    expect(isJobActive(job('done'))).toBe(false)
    expect(isJobActive(job('failed'))).toBe(false)
  })

  it('treats a card that has never been fetched as inactive', () => {
    // The GET carries job: null for a card with no history; polling must not start.
    expect(isJobActive(null)).toBe(false)
    expect(isJobActive(undefined)).toBe(false)
  })
})
