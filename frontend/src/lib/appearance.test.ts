// Tests for layout variables + appearance persistence (width sliders).
import { afterEach, describe, expect, it } from 'vitest'
import {
  applyLayout,
  applyStoredAppearance,
  DEFAULT_LAYOUT,
  loadAppearance,
  saveAppearance,
} from './appearance'
import { DEFAULT_SIZES } from './presets'

afterEach(() => localStorage.clear())

describe('applyLayout', () => {
  it('sets the workspace width and list-pane split as CSS variables', () => {
    applyLayout({ maxWidth: 1600, listWidth: 45 })
    const root = document.documentElement
    expect(root.style.getPropertyValue('--layout-max-width')).toBe('1600px')
    expect(root.style.getPropertyValue('--list-pane-width')).toBe('45%')
  })
})

describe('appearance persistence', () => {
  it('round-trips theme, sizes, and layout through localStorage', () => {
    saveAppearance({
      theme: 'warm-dark-classic',
      sizes: { ...DEFAULT_SIZES, body: 17 },
      layout: { maxWidth: 1500, listWidth: 33 },
    })
    const loaded = loadAppearance()
    expect(loaded.theme).toBe('warm-dark-classic')
    expect(loaded.sizes.body).toBe(17)
    expect(loaded.layout).toEqual({ maxWidth: 1500, listWidth: 33 })
  })

  it('returns the defaults when nothing is stored or the entry is corrupt', () => {
    expect(loadAppearance().layout).toEqual(DEFAULT_LAYOUT)
    localStorage.setItem('spyglass-appearance', '{not json')
    expect(loadAppearance().theme).toBe('anthropic-coral-classic')
  })

  it('applies the stored appearance on startup', () => {
    saveAppearance({
      theme: 'warm-dark-classic',
      sizes: DEFAULT_SIZES,
      layout: { maxWidth: 1400, listWidth: 50 },
    })
    applyStoredAppearance()
    const root = document.documentElement
    expect(root.dataset.theme).toBe('warm-dark-classic')
    expect(root.style.getPropertyValue('--layout-max-width')).toBe('1400px')
    expect(root.style.getPropertyValue('--list-pane-width')).toBe('50%')
  })
})
