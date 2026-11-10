// Tests for text helpers.
import { describe, expect, it } from 'vitest'
import { stripHtml } from './text'

describe('stripHtml', () => {
  it('removes tags and collapses whitespace', () => {
    expect(stripHtml('<p>Hello <b>world</b></p>')).toBe('Hello world')
  })

  it('drops img and other self-closing tags', () => {
    expect(stripHtml('<img src="x.png"/>Caption text')).toBe('Caption text')
  })

  it('decodes common HTML entities', () => {
    expect(stripHtml('A &amp; B &lt; C')).toBe('A & B < C')
  })

  it('returns plain text unchanged', () => {
    expect(stripHtml('just text')).toBe('just text')
  })
})
