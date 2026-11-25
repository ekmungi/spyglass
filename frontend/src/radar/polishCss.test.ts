// Guards for the stylesheet polish that jsdom cannot render: each rule is looked up in the CSS text.
// They cover row details, form controls, tooltips over the pinned bars, section headings and widths.
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const feedCss = read('./feed/feed.css')
const readerCss = read('./reader/reader.css')
const todayCss = read('./today/today.css')
const baseCss = read('./ui/base.css')
const overlaysCss = read('./ui/overlays.css')
const primitivesCss = read('./ui/primitives.css')
const tokensCss = read('./ui/tokens.css')

/** The body of the first rule whose selector list contains `selector`. */
function rule(source: string, selector: string): string {
  const start = source.indexOf(selector)
  if (start < 0) return ''
  return source.slice(source.indexOf('{', start) + 1, source.indexOf('}', start))
}

interface CssRule {
  selectors: string[]
  body: string
}

/** Every rule of a style sheet, comments removed and selectors normalised to single spaces. Rules
 *  inside an @media block are listed like any other rule. */
function rules(source: string): CssRule[] {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, '')
  return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors, body]) => ({
    selectors: selectors.split(',').map((selector) => selector.trim().replace(/\s+/g, ' ')),
    body,
  }))
}

/** The body of the first rule whose selector list holds exactly `selector`, or '' when none does. */
function ruleFor(source: string, selector: string): string {
  return rules(source).find((entry) => entry.selectors.includes(selector))?.body ?? ''
}

/** The value of `property` in a rule body, whitespace collapsed, or '' when it is not set. */
function valueOf(body: string, property: string): string {
  const match = new RegExp(`(?:^|[;{\\s])${property}\\s*:\\s*([^;]+);`).exec(body)
  return match ? match[1].trim().replace(/\s+/g, ' ') : ''
}

/** How many class, attribute and pseudo-class parts a selector has (the middle number of its
 *  specificity). The selectors compared here have no ids, :is() or :not(). */
function classWeight(selector: string): number {
  return (selector.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) ?? []).length
}

const FIELD_SHADE = 'color-mix(in srgb, var(--ink) 6%, var(--paper))'
const HEADING_TINT = 'color-mix(in srgb, var(--accent) 6%, var(--paper))'

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

describe('form controls', () => {
  it('gives a menu the height and the text size of a text box', () => {
    const select = ruleFor(primitivesCss, '.r-select select')
    expect(valueOf(select, 'height')).toBe('40px')
    expect(valueOf(select, 'font-size')).toBe('var(--text-base)')
  })

  it('gives text boxes, text areas and menus one shade that differs from the page', () => {
    const input = valueOf(ruleFor(overlaysCss, '.r-input'), 'background')
    const textarea = valueOf(ruleFor(overlaysCss, '.r-textarea'), 'background')
    const select = valueOf(ruleFor(primitivesCss, '.r-select select'), 'background')
    expect(input).toBe(FIELD_SHADE)
    expect(textarea).toBe(FIELD_SHADE)
    // The menu's background also carries its arrow image, after the same colour.
    expect(select.startsWith(`${FIELD_SHADE} `)).toBe(true)
    expect(input).not.toBe('var(--paper)')
  })
})

describe('tooltips over the pinned bars', () => {
  it('raises a pointed-at or focused tooltip to layer 60, over the row rules that keep it at 1', () => {
    const raised = rules(primitivesCss).find((entry) => valueOf(entry.body, 'z-index') === '60' && entry.selectors.some((selector) => selector.includes('.r-tip')))
    expect(raised).toBeDefined()
    const selectors = raised?.selectors ?? []
    expect(selectors.some((selector) => selector.endsWith(':hover'))).toBe(true)
    expect(selectors.some((selector) => selector.endsWith(':focus-within'))).toBe(true)

    // The row rules stay: they keep a row's buttons above the row's stretched link.
    for (const [source, row] of [[todayCss, '.r-story .r-tip'], [feedCss, '.r-feedrow .r-tip']] as const) {
      expect(valueOf(ruleFor(source, row), 'z-index')).toBe('1')
      // The page sheets load after the kit, so the raising rule must outrank them, not tie with them.
      for (const selector of selectors) expect(classWeight(selector)).toBeGreaterThan(classWeight(row))
    }
  })
})

describe('section headings', () => {
  it('sets the title in normal letters at the heading size, semi-bold', () => {
    const title = ruleFor(primitivesCss, '.r-section-heading__title')
    expect(valueOf(title, 'font-size')).toBe('var(--text-heading)')
    expect(valueOf(title, 'font-weight')).toBe('600')
    expect(title).not.toMatch(/font-variant-caps|letter-spacing/)
    expect(valueOf(ruleFor(tokensCss, ':root'), '--text-heading')).toBe('calc(17px * var(--type-scale, 1))')
  })

  it('draws the heading as a tinted, rounded bar with no line under it', () => {
    const bar = ruleFor(primitivesCss, '.r-section-heading')
    expect(valueOf(bar, 'background')).toBe(HEADING_TINT)
    expect(valueOf(bar, 'padding')).toBe('7px var(--space-3)')
    expect(valueOf(bar, 'border-radius')).toBe('var(--radius-md)')
    expect(bar).not.toMatch(/border-bottom/)
  })

  it("draws the Feed's day heading as the same bar across the full width, 47 pixels high", () => {
    expect(valueOf(ruleFor(feedCss, '.r-page--feed'), '--feed-day-h')).toBe('47px')
    const day = ruleFor(feedCss, '.r-feed-day')
    expect(valueOf(day, 'padding')).toBe('3px 0')
    const title = ruleFor(feedCss, '.r-feed-day__title')
    expect(valueOf(title, 'flex')).toBe('1')
    expect(valueOf(title, 'background')).toBe(HEADING_TINT)
    expect(valueOf(title, 'font-size')).toBe('var(--text-heading)')
    expect(title).not.toMatch(/font-variant-caps|letter-spacing/)
  })
})

describe('page widths', () => {
  it('makes a wide page 920 pixels', () => {
    expect(valueOf(ruleFor(baseCss, '.r-page--wide'), 'max-width')).toBe('920px')
  })
})
