// Guards for search-field focus that jsdom cannot render, checked in the style sheet text: the Help
// search and the Papers search show focus as the Feed search does, a thin accent border, because a
// focus ring on :focus-within also appears on a mouse click and looks like a thick blue frame.
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const help = read('./help.css')
const papers = read('../pages/papers/papers.css')

/** The body of the first rule whose selector list is exactly `selector`, or '' when there is none. */
function ruleBody(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm').exec(css)
  return match ? match[1] : ''
}

describe('search field focus', () => {
  it("gives the Help search the Feed's focus border", () => {
    const focused = ruleBody(help, '.rh-search:focus-within')
    expect(focused).toContain('border-color: var(--accent)')
    expect(focused).not.toContain('--focus-ring')
    expect(ruleBody(help, '.rh-search input:focus-visible')).toContain('box-shadow: none')
  })

  it('gives the Papers search the same thin border, without the form-field halo', () => {
    expect(ruleBody(papers, '.rpp-search__input:focus-visible')).toContain('box-shadow: none')
  })
})
