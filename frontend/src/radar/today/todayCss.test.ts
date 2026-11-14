// Guards for Today's column that jsdom cannot render, checked in the style sheet text: the opening
// sentences and the notice span the shared column, like Today's story rows and the Feed's rows. A
// character cap made the top of Today wrap narrower than the rows whenever the column was wider than it.
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
  it.each(['.r-masthead__opening', '.r-masthead__notice'])('lets %s span the shared column', (selector) => {
    const body = ruleBody(today, selector)
    expect(body).not.toBe('')
    expect(body).not.toMatch(/max-width/)
  })
})
