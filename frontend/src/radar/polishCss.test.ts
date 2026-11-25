// Guards for the stylesheet polish that jsdom cannot render: each rule is looked up in the CSS text.
// They cover row details, form controls, tooltips over the pinned bars, the thumbs, section headings
// and widths.
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
 *  specificity). A :has(), :is() or :not() counts as its argument, as in CSS, and a :where() counts
 *  nothing. The selectors compared here have no ids and give those functions a single argument. */
function classWeight(selector: string): number {
  const counted = selector.replace(/:where\([^)]*\)/g, '').replace(/:(?:has|is|not)\(/g, '(')
  return (counted.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) ?? []).length
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
  /** The rule that raises a tooltip's wrapper: a `.r-tip` selector ending in :hover, with a layer. */
  const raisedRule = () =>
    rules(primitivesCss).find((entry) => valueOf(entry.body, 'z-index') !== '' && entry.selectors.some((selector) => /^\.r-tip[.\w-]*:hover$/.test(selector)))

  it('raises the wrapper only while its bubble shows: on hover, or on keyboard focus and not after a click', () => {
    const selectors = raisedRule()?.selectors ?? []
    expect(selectors).toHaveLength(2)
    expect(selectors.some((selector) => selector.endsWith(':hover'))).toBe(true)
    expect(selectors.some((selector) => selector.endsWith(':has(:focus-visible)'))).toBe(true)
    // A mouse click leaves the focus on the button, so :focus-within would keep a clicked row's
    // button over the pinned bars after the list scrolls.
    expect(selectors.join(' ')).not.toMatch(/focus-within/)
    // Each raising condition is a condition that shows the bubble.
    const showing = rules(primitivesCss)
      .filter((entry) => valueOf(entry.body, 'opacity') === '1')
      .flatMap((entry) => entry.selectors)
    for (const selector of selectors) expect(showing).toContain(`${selector.replace('.r-tip.r-tip', '.r-tip')} .r-tip__bubble`)
  })

  it('lifts it to layer 40: over the highest pinned bar and under an open menu list', () => {
    const layer = Number(valueOf(raisedRule()?.body ?? '', 'z-index'))
    expect(layer).toBe(40)
    const highestBar = Number(valueOf(ruleFor(read('./assistant/assistant.css'), '.r-askpill-slot'), 'z-index'))
    const menuList = Number(valueOf(ruleFor(primitivesCss, '.r-menu__list'), 'z-index'))
    expect(highestBar).toBe(30)
    expect(layer).toBeGreaterThan(highestBar)
    expect(layer).toBeLessThan(menuList)
  })

  it('outranks the row rules that keep a row button at layer 1, which stay', () => {
    const selectors = raisedRule()?.selectors ?? []
    expect(selectors.length).toBeGreaterThan(0)
    // The row rules stay: they keep a row's buttons above the row's stretched link.
    for (const [source, row] of [[todayCss, '.r-story .r-tip'], [feedCss, '.r-feedrow .r-tip']] as const) {
      expect(valueOf(ruleFor(source, row), 'z-index')).toBe('1')
      // The page sheets load after the kit, so the raising rule must outrank them, not tie with them.
      for (const selector of selectors) expect(classWeight(selector)).toBeGreaterThan(classWeight(row))
    }
  })
})

describe('thumbs', () => {
  it('take no pointer while hidden, so a tap cannot vote on an invisible button, and take it again wherever they show', () => {
    const rest = ruleFor(primitivesCss, '.r-votes')
    expect(valueOf(rest, 'opacity')).toBe('0')
    expect(valueOf(rest, 'pointer-events')).toBe('none')
    const reveal = rules(primitivesCss).find((entry) => entry.selectors.includes('.r-votes--always'))
    // Keyboard focus still reveals them: the pointer setting does not affect focus.
    expect(reveal?.selectors).toEqual(expect.arrayContaining(['li:hover .r-votes', 'li:focus-within .r-votes', '.r-votes:focus-within', '.r-votes.is-voted', '.r-votes--always']))
    expect(valueOf(reveal?.body ?? '', 'opacity')).toBe('1')
    expect(valueOf(reveal?.body ?? '', 'pointer-events')).toBe('auto')
  })

  it('show on every row of a device without hover, as Save does on the Feed and on Today', () => {
    // The media block is read as a whole: the rule for the thumbs must sit inside "(hover: none)".
    const block = /@media \(hover: none\) \{([\s\S]*?\})\s*\}/.exec(primitivesCss.replace(/\/\*[\s\S]*?\*\//g, ''))
    const inside = rules(block?.[1] ?? '').find((entry) => entry.selectors.includes('.r-votes'))
    expect(valueOf(inside?.body ?? '', 'opacity')).toBe('1')
    expect(valueOf(inside?.body ?? '', 'pointer-events')).toBe('auto')
  })

  it("show on Today's selected row, as Save does, so an arrow turn that moves the selection reveals them", () => {
    const selected = ruleFor(todayCss, '.r-story.is-selected .r-votes')
    expect(valueOf(selected, 'opacity')).toBe('1')
    expect(valueOf(selected, 'pointer-events')).toBe('auto')
  })
})

describe('hidden panels', () => {
  it('stay hidden whatever display a page rule gives them', () => {
    expect(valueOf(ruleFor(baseCss, '[hidden]'), 'display')).toBe('none !important')
  })
})

describe("Today's lead story", () => {
  it('sets its why at the heading size through the shared token', () => {
    expect(valueOf(ruleFor(todayCss, '.r-brief__list--lead > .r-story:first-child .r-story__why'), 'font-size')).toBe('var(--text-heading)')
  })
})

describe("the reader's step buttons", () => {
  it('keep the faint disabled look at either end, with no press, while they stay focusable', () => {
    const end = ruleFor(readerCss, '.r-readerbar__nav .r-iconbtn[aria-disabled="true"]')
    expect(valueOf(end, 'opacity')).toBe(valueOf(ruleFor(primitivesCss, '.r-iconbtn:disabled'), 'opacity'))
    expect(valueOf(end, 'cursor')).toBe('not-allowed')
    expect(valueOf(ruleFor(readerCss, '.r-readerbar__nav .r-iconbtn[aria-disabled="true"]:active'), 'translate')).toBe('none')
  })
})

describe('the Filters button of the Feed', () => {
  it('turns to the accent colour while a filter is on, with room for the count beside the icon', () => {
    const active = ruleFor(feedCss, '.r-feed-filter.is-active')
    expect(valueOf(active, 'color')).toBe('var(--accent)')
    expect(valueOf(active, 'width')).toBe('auto')
    expect(valueOf(ruleFor(feedCss, '.r-feed-filter__count'), 'font-size')).toBe('var(--text-xs)')
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
