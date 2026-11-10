// Tests for the theme preset system: 48 generated presets, runtime application.
import { describe, expect, it } from 'vitest'
import {
  applyPreset,
  applySizes,
  blend,
  buildPresets,
  DEFAULT_SIZES,
  resetSizes,
} from './presets'

const HEX = /^#[0-9a-f]{6}$/

describe('buildPresets', () => {
  it('generates 48 presets (12 palettes x 4 treatments)', () => {
    expect(buildPresets()).toHaveLength(48)
  })

  it('gives every preset a unique name and valid hex tokens', () => {
    const presets = buildPresets()
    const names = new Set(presets.map((p) => p.name))
    expect(names.size).toBe(48)
    for (const preset of presets) {
      for (const value of Object.values(preset.tokens)) {
        expect(value).toMatch(HEX)
      }
    }
  })

  it('includes the two defaults from the design: v01 light and v41 dark', () => {
    const names = buildPresets().map((p) => p.name)
    expect(names).toContain('anthropic-coral-classic')
    expect(names).toContain('warm-dark-classic')
  })
})

describe('blend', () => {
  it('mixes two colors by weight', () => {
    expect(blend('#000000', '#ffffff', 0.5)).toBe('#808080')
    expect(blend('#000000', '#ffffff', 0)).toBe('#000000')
    expect(blend('#000000', '#ffffff', 1)).toBe('#ffffff')
  })
})

describe('applyPreset', () => {
  it('sets the data-theme attribute and all color variables on the root', () => {
    const preset = buildPresets().find((p) => p.name === 'warm-dark-classic')!
    applyPreset(preset)
    const root = document.documentElement
    expect(root.dataset.theme).toBe('warm-dark-classic')
    expect(root.style.getPropertyValue('--color-canvas')).toBe(preset.tokens.canvas)
    expect(root.style.getPropertyValue('--color-accent')).toBe(preset.tokens.accent)
  })

  it('derives a surface token slightly shifted from the canvas toward the ink', () => {
    const preset = buildPresets().find((p) => p.name === 'anthropic-coral-classic')!
    applyPreset(preset)
    const surface = document.documentElement.style.getPropertyValue('--color-surface')
    expect(surface).toMatch(HEX)
    expect(surface).not.toBe(preset.tokens.canvas)
  })

  it('sets relevance status colors matched to the preset darkness', () => {
    const presets = buildPresets()
    const root = document.documentElement
    applyPreset(presets.find((p) => p.name === 'anthropic-coral-classic')!)
    const lightOk = root.style.getPropertyValue('--color-ok')
    applyPreset(presets.find((p) => p.name === 'warm-dark-classic')!)
    const darkOk = root.style.getPropertyValue('--color-ok')
    expect(lightOk).toMatch(HEX)
    expect(darkOk).toMatch(HEX)
    expect(lightOk).not.toBe(darkOk)
    expect(root.style.getPropertyValue('--color-out')).toMatch(HEX)
  })
})

describe('sizes', () => {
  it('applies user sizes as CSS variables and resets to the locked defaults', () => {
    applySizes({ ...DEFAULT_SIZES, body: 17 })
    const root = document.documentElement
    expect(root.style.getPropertyValue('--font-size-body')).toBe('17px')
    resetSizes()
    expect(root.style.getPropertyValue('--font-size-body')).toBe(`${DEFAULT_SIZES.body}px`)
    expect(root.style.getPropertyValue('--leading-body')).toBe(`${DEFAULT_SIZES.lineHeight}`)
  })
})
