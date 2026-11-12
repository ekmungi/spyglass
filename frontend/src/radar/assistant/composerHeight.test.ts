// Tests for the composer's growth limit.
import { describe, expect, it } from 'vitest'
import { maxComposerHeight } from './composerHeight'

describe('maxComposerHeight', () => {
  it('is six lines of the text box plus its padding', () => {
    expect(maxComposerHeight({ lineHeight: '22px', fontSize: '15px', paddingTop: '4px', paddingBottom: '4px' })).toBe(140)
  })

  it('works out a line from the font size when the line height is "normal"', () => {
    expect(maxComposerHeight({ lineHeight: 'normal', fontSize: '15px', paddingTop: '0px', paddingBottom: '0px' })).toBe(126)
  })

  it('still answers with an unreadable style', () => {
    expect(maxComposerHeight({ lineHeight: '', fontSize: '', paddingTop: '', paddingBottom: '' })).toBe(126)
  })
})
