// Tests for isNoCredit: billing failures are recognised, other errors are not.
import { describe, expect, it } from 'vitest'
import { isNoCredit } from './errorKind'

describe('isNoCredit', () => {
  it('recognises the provider wording and the 402 status', () => {
    expect(isNoCredit('Provider returned an error: this account has no credit left')).toBe(true)
    expect(isNoCredit('OpenRouter 402: Insufficient credits')).toBe(true)
    expect(isNoCredit('Payment Required')).toBe(true)
    expect(isNoCredit('The request failed.', 402)).toBe(true)
  })

  it('does not flag other failures', () => {
    expect(isNoCredit('The engine stopped responding.')).toBe(false)
    expect(isNoCredit('Rate limit reached (429).', 429)).toBe(false)
    expect(isNoCredit('model 4020 not found')).toBe(false)
    expect(isNoCredit(null)).toBe(false)
    expect(isNoCredit(undefined)).toBe(false)
  })
})
