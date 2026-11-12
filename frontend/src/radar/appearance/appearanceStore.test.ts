// Tests for the appearance store: persistence, the CSS variables it sets, validation of stored
// values, the text-width limits and lazy font loading.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getAppearance,
  initAppearance,
  loadFont,
  resetAppearance,
  setAppearance,
  STORAGE_KEYS,
  stepTextWidth,
} from './appearanceStore'
import { clampTextWidth, headingMinWeight, READING_FONTS, TEXT_WIDTH, textWidthLabel, textWidthWord, UI_FONTS } from './catalog'

const root = document.documentElement
const prop = (name: string) => root.style.getPropertyValue(name)

beforeEach(() => {
  window.localStorage.clear()
  root.removeAttribute('style')
  root.removeAttribute('data-theme')
  initAppearance()
})

describe('applying and remembering', () => {
  it('starts with the designed defaults: Fira Sans for reading and the interface', () => {
    expect(getAppearance()).toEqual({ theme: 'system', readingFont: 'fira-sans', uiFont: 'fira-sans', textSize: 'comfortable', textWidth: 680 })
    expect(prop('--font-serif')).toContain('"Fira Sans"')
    expect(prop('--font-sans')).toContain('"Fira Sans"')
    expect(prop('--type-scale')).toBe('1')
    expect(prop('--measure')).toBe('680px')
    expect(prop('--measure-read')).toBe('700px')
    // A sans reading font gives headlines a minimum weight of 600, so the default sets it at first paint.
    expect(prop('--heading-min')).toBe('600')
    expect(root.hasAttribute('data-theme')).toBe(false)
  })

  it('sets the font and size variables on the document and stores each choice', () => {
    setAppearance({ readingFont: 'lora', uiFont: 'figtree', textSize: 'large', theme: 'dark' })
    expect(prop('--font-serif')).toContain('"Lora Variable"')
    expect(prop('--font-sans')).toContain('"Figtree Variable"')
    expect(prop('--type-scale')).toBe('1.12')
    expect(root.getAttribute('data-theme')).toBe('dark')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEYS.readingFont) ?? 'null')).toBe('lora')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEYS.textSize) ?? 'null')).toBe('large')
  })

  it('applies stored choices at start-up, before anything renders', () => {
    window.localStorage.setItem(STORAGE_KEYS.readingFont, JSON.stringify('literata'))
    window.localStorage.setItem(STORAGE_KEYS.uiFont, JSON.stringify('system'))
    window.localStorage.setItem(STORAGE_KEYS.textSize, JSON.stringify('compact'))
    window.localStorage.setItem(STORAGE_KEYS.textWidth, JSON.stringify(900))
    initAppearance()
    expect(prop('--font-serif')).toContain('"Literata Variable"')
    expect(prop('--font-sans')).toContain('system-ui')
    expect(prop('--type-scale')).toBe('0.92')
    expect(prop('--measure')).toBe('900px')
    expect(prop('--measure-read')).toBe('920px')
  })

  it('falls back to the default for a stored value it does not know', () => {
    window.localStorage.setItem(STORAGE_KEYS.readingFont, JSON.stringify('comic-sans'))
    window.localStorage.setItem(STORAGE_KEYS.textWidth, JSON.stringify(99999))
    window.localStorage.setItem(STORAGE_KEYS.theme, '"purple"')
    initAppearance()
    expect(getAppearance()).toMatchObject({ readingFont: 'fira-sans', theme: 'system', textWidth: 1100 })
  })

  it('lets the "Sans" reading font follow the interface font and gives sans headings weight 600', () => {
    setAppearance({ uiFont: 'dm-sans', readingFont: 'sans' })
    expect(prop('--font-serif')).toBe(prop('--font-sans'))
    expect(prop('--heading-min')).toBe('600')
    setAppearance({ readingFont: 'fira-sans' })
    expect(prop('--heading-min')).toBe('600')
    setAppearance({ readingFont: 'source-serif-4' })
    expect(prop('--heading-min')).toBe('0')
    setAppearance({ readingFont: 'newsreader' })
    expect(prop('--heading-min')).toBe('0')
    expect(headingMinWeight('nunito-sans')).toBe(600)
    expect(headingMinWeight('fira-sans')).toBe(600)
  })

  it('resets every choice, theme and width included', () => {
    setAppearance({ readingFont: 'lora', uiFont: 'geist', textSize: 'large', theme: 'dark', textWidth: 1000 })
    resetAppearance()
    expect(getAppearance()).toEqual({ theme: 'system', readingFont: 'fira-sans', uiFont: 'fira-sans', textSize: 'comfortable', textWidth: 680 })
    expect(prop('--measure')).toBe('680px')
    expect(prop('--font-serif')).toContain('"Fira Sans"')
    expect(prop('--heading-min')).toBe('600')
    expect(root.hasAttribute('data-theme')).toBe(false)
  })
})

describe('text width', () => {
  it('steps by 40px and stops at both ends', () => {
    stepTextWidth(-TEXT_WIDTH.quickStep)
    expect(getAppearance().textWidth).toBe(640)
    for (let i = 0; i < 10; i += 1) stepTextWidth(-TEXT_WIDTH.quickStep)
    expect(getAppearance().textWidth).toBe(TEXT_WIDTH.min)
    for (let i = 0; i < 30; i += 1) stepTextWidth(TEXT_WIDTH.quickStep)
    expect(getAppearance().textWidth).toBe(TEXT_WIDTH.max)
    expect(prop('--measure')).toBe('1100px')
  })

  it('keeps a value inside the range and on the slider grid', () => {
    expect(clampTextWidth(100)).toBe(560)
    expect(clampTextWidth(2000)).toBe(1100)
    expect(clampTextWidth(691)).toBe(700)
    expect(clampTextWidth('wide')).toBe(680)
    expect(clampTextWidth(Number.NaN)).toBe(680)
  })

  it('describes a width with a plain word and the number', () => {
    expect(textWidthLabel(680)).toBe('Medium · 680px')
    expect([560, 700, 800, 1100].map(textWidthWord)).toEqual(['Narrow', 'Medium', 'Wide', 'Extra wide'])
  })
})

describe('lazy font loading', () => {
  it('fetches a font once, and never for the bundled defaults or system choices', async () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const option = { id: 'demo', label: 'Demo', group: 'more' as const, stack: 'Demo', load }
    await loadFont(option)
    await loadFont(option)
    expect(load).toHaveBeenCalledTimes(1)
    const bundled = [
      READING_FONTS.find((f) => f.id === 'fira-sans'), UI_FONTS.find((f) => f.id === 'fira-sans'),
      READING_FONTS.find((f) => f.id === 'newsreader'), READING_FONTS.find((f) => f.id === 'sans'),
      UI_FONTS.find((f) => f.id === 'inter'), UI_FONTS.find((f) => f.id === 'system'),
    ]
    expect(bundled.every((font) => font?.load === null)).toBe(true)
  })

  it('survives a failed font download (the fallback stack covers it)', async () => {
    const option = { id: 'broken', label: 'Broken', group: 'more' as const, stack: 'Broken', load: () => Promise.reject(new Error('offline')) }
    await expect(loadFont(option)).resolves.toBeUndefined()
  })

  it('puts the default first, then the notes-theme fonts, then the rest', () => {
    expect(READING_FONTS.map((f) => f.group).filter((g, i, all) => all.indexOf(g) === i)).toEqual(['default', 'notes', 'more'])
    expect(UI_FONTS.slice(0, 3).map((f) => [f.id, f.group])).toEqual([['fira-sans', 'default'], ['source-sans-3', 'notes'], ['nunito-sans', 'notes']])
    expect(READING_FONTS.slice(0, 3).map((f) => [f.id, f.group])).toEqual([['fira-sans', 'default'], ['source-sans-3', 'notes'], ['nunito-sans', 'notes']])
    expect(READING_FONTS.find((f) => f.id === 'newsreader')?.group).toBe('more')
    expect(UI_FONTS.find((f) => f.id === 'inter')?.group).toBe('more')
  })
})
