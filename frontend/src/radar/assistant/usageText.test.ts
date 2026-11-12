// Tests for the words that describe token figures.
import { describe, expect, it } from 'vitest'
import { describeUsage, formatCount, formatShare } from './usageText'

describe('usageText', () => {
  it('formats counts with separators and shares as whole percentages', () => {
    expect(formatCount(12400)).toBe('12,400')
    expect(formatShare(0.914)).toBe('91%')
    expect(formatShare(0)).toBe('0%')
    expect(formatShare(0.004)).toBe('under 1%')
  })

  it('describes what the model read, how much came from cache and what it wrote', () => {
    expect(describeUsage({ context_tokens: 12400, cached_share: 0.91, output_tokens: 380, model: 'sonnet' })).toBe(
      'sonnet · Read 12,400 tokens, 91% from cache · wrote 380',
    )
  })

  it('leaves out what the provider did not report', () => {
    expect(describeUsage({ output_tokens: 380 })).toBe('wrote 380')
    expect(describeUsage({ context_tokens: 500 })).toBe('Read 500 tokens')
    expect(describeUsage({})).toBe('')
  })
})
