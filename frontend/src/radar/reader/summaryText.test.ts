// Tests for spotting a summary line that repeats the start of the document.
import { describe, expect, it } from 'vitest'
import { repeatsDocumentStart } from './summaryText'

const ABSTRACT = 'We study self-supervised pretraining for surgical video and compare seven recipes across seven downstream tasks.'

describe('repeatsDocumentStart', () => {
  it('finds an abstract that the document opens with, ignoring markup and punctuation', () => {
    const html = `<h2>Abstract</h2><p>We study <em>self-supervised</em> pretraining for surgical video, and compare seven recipes across seven downstream tasks.</p><p>1 Introduction</p>`
    expect(repeatsDocumentStart(ABSTRACT, html)).toBe(true)
  })

  it('does not match different text, a short line or a missing document', () => {
    expect(repeatsDocumentStart(ABSTRACT, '<p>Something else entirely about agent harnesses and tool permissions in practice today.</p>')).toBe(false)
    expect(repeatsDocumentStart('Short line', '<p>Short line</p>')).toBe(false)
    expect(repeatsDocumentStart(ABSTRACT, null)).toBe(false)
  })

  it('ignores a match that only appears deep in the document', () => {
    const filler = '<p>' + 'unrelated words '.repeat(400) + '</p>'
    expect(repeatsDocumentStart(ABSTRACT, `${filler}<p>${ABSTRACT}</p>`)).toBe(false)
  })
})
