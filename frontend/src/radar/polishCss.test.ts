// Guards for the stylesheet polish that jsdom cannot render: each rule is looked up in the CSS text.
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const feedCss = read('./feed/feed.css')
const readerCss = read('./reader/reader.css')
const todayCss = read('./today/today.css')

/** The body of the first rule whose selector list contains `selector`. */
function rule(source: string, selector: string): string {
  const start = source.indexOf(selector)
  if (start < 0) return ''
  return source.slice(source.indexOf('{', start) + 1, source.indexOf('}', start))
}

describe('stylesheet polish', () => {
  it('shows the Save control faintly at rest on Today and Feed rows', () => {
    expect(rule(todayCss, '.r-story .r-save {')).toMatch(/opacity:\s*0\.\d+/)
    expect(rule(feedCss, '.r-feedrow .r-save {')).toMatch(/opacity:\s*0\.\d+/)
  })

  it('keeps the keyboard focus ring 2px away from the row text', () => {
    expect(rule(todayCss, '.r-story__link:focus-visible::after')).toMatch(/inset:\s*-2px/)
    expect(rule(feedCss, '.r-feedrow__link:focus-visible::after')).toMatch(/inset:\s*-2px/)
  })

  it('clamps very long titles at four lines in lists', () => {
    for (const [source, selector] of [[todayCss, '.r-story__headline {'], [feedCss, '.r-feedrow__headline {']] as const) {
      expect(rule(source, selector)).toMatch(/-webkit-line-clamp:\s*4/)
    }
  })

  it('sets display equations at the body size and not the size of data tables', () => {
    const reader = readerCss
    expect(rule(reader, '.r-prose math[display="block"]')).toMatch(/font-size:\s*var\(--text-read\)/)
    expect(rule(reader, '.r-prose table:has(math[display="block"])')).toMatch(/font-size:\s*var\(--text-read\)/)
  })
})
