// Guards for Today's layout that jsdom cannot render, checked in the style sheet text. The page is 940
// pixels wide, and the top section sets its stories in two columns, with the lead story of its first
// page across both. The opening is capped by the layout token for a reading column and nothing else:
// a character cap once made it wrap narrower than intended whenever the column changed. The closing
// line about unjudged items spans the page column.
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// The path goes through a variable so Vite does not rewrite it into a served asset address.
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const today = read('./today.css')

/** The body of the first rule whose selector list is exactly `selector`, or '' when there is none. */
function ruleBody(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm').exec(css)
  return match ? match[1] : ''
}

describe("Today's column", () => {
  it('lets the closing line about unjudged items span the page column', () => {
    const body = ruleBody(today, '.r-brief__endnote')
    expect(body).not.toBe('')
    expect(body).not.toMatch(/max-width/)
  })

  it('caps the opening at the reading column token and by no other width', () => {
    const widths = Array.from(ruleBody(today, '.r-masthead__opening').matchAll(/max-width:\s*([^;]+);/g), (match) => match[1].trim())
    expect(widths).toEqual(['var(--measure)'])
  })

  it('makes the page 940 pixels wide', () => {
    expect(ruleBody(today, '.r-page--brief')).toMatch(/max-width:\s*940px/)
  })

  it('sets the top section in two columns, with the lead story of the first page across both', () => {
    expect(ruleBody(today, '.r-brief__section--top .r-brief__list')).toMatch(/grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
    expect(ruleBody(today, '.r-brief__list--lead > .r-story:first-child')).toMatch(/grid-column:\s*1\s*\/\s*-1/)
  })

  it('no longer styles a notice in the masthead', () => {
    expect(ruleBody(today, '.r-masthead__notice')).toBe('')
  })
})
