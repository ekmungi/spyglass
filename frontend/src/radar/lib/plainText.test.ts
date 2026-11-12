// Tests for plainText: titles with entities or stray markup come out as plain words.
import { describe, expect, it } from 'vitest'
import { plainText } from './plainText'

describe('plainText', () => {
  it('leaves an ordinary title alone (and collapses stray whitespace)', () => {
    expect(plainText('Aster 4 is here')).toBe('Aster 4 is here')
    expect(plainText('  two   spaces\n here ')).toBe('two spaces here')
  })

  it('decodes entities', () => {
    expect(plainText('Q&amp;A: How it works')).toBe('Q&A: How it works')
    expect(plainText('Fish &amp; chips &#8211; &quot;fresh&quot;')).toBe('Fish & chips – "fresh"')
  })

  it('keeps a bare ampersand', () => {
    expect(plainText('Scalable AI Governance & Evaluation')).toBe('Scalable AI Governance & Evaluation')
  })

  it('keeps the words of a title wrapped in a link element', () => {
    const wrapped = '<a href="https://example.org/x" hreflang="en">Strengthening Healthcare Delivery</a>'
    expect(plainText(wrapped)).toBe('Strengthening Healthcare Delivery')
  })

  it('never yields markup: scripts, images and double-encoded tags come out as text only', () => {
    expect(plainText('Hi <script>alert(1)</script><img src=x onerror=alert(1)>there')).toBe('Hi alert(1)there')
    // Decoded once only: an escaped tag stays visible as text, to be rendered by React as text.
    expect(plainText('&lt;b&gt;bold&lt;/b&gt;')).toBe('<b>bold</b>')
  })

  it('handles empty values', () => {
    expect(plainText(null)).toBe('')
    expect(plainText(undefined)).toBe('')
    expect(plainText('')).toBe('')
  })
})
