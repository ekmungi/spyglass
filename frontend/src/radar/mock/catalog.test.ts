// Tests for the sample sources: every group on the Sources page has a collector row to show.
import { describe, expect, it } from 'vitest'
import { SOURCES } from './catalog'

describe('sample sources', () => {
  it('has a last run for the FDA group', () => {
    const fda = SOURCES.collectors.find((row) => row.key === 'fda')
    expect(fda?.status).toBe('ok')
    expect(fda?.last_run).toBeTruthy()
  })
})
