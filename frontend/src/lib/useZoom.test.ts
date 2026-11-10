// Tests for the zoom persistence helpers (useZoom.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applyZoom,
  clampZoom,
  loadZoom,
  saveZoom,
  ZOOM_DEFAULT,
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_STORAGE_KEY,
} from './useZoom'

describe('clampZoom', () => {
  it('returns the value unchanged when within bounds', () => {
    expect(clampZoom(1.0)).toBe(1.0)
    expect(clampZoom(ZOOM_MIN)).toBe(ZOOM_MIN)
    expect(clampZoom(ZOOM_MAX)).toBe(ZOOM_MAX)
  })

  it('clamps below the minimum to ZOOM_MIN', () => {
    expect(clampZoom(0.1)).toBe(ZOOM_MIN)
    expect(clampZoom(-5)).toBe(ZOOM_MIN)
  })

  it('clamps above the maximum to ZOOM_MAX', () => {
    expect(clampZoom(2.0)).toBe(ZOOM_MAX)
    expect(clampZoom(999)).toBe(ZOOM_MAX)
  })

  it('rounds to one decimal place to avoid float accumulation', () => {
    // 0.1 + 0.2 in JS = 0.30000000000000004; clamp should round it to 0.3
    expect(clampZoom(0.1 + 0.2 + 0.5)).toBe(0.8)
  })
})

describe('loadZoom', () => {
  let store: Record<string, string> = {}

  beforeEach(() => {
    store = {}
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => {
        store[key] = value
      },
      removeItem: (key: string) => {
        delete store[key]
      },
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('returns ZOOM_DEFAULT when nothing is stored', () => {
    expect(loadZoom()).toBe(ZOOM_DEFAULT)
  })

  it('returns the stored value when valid', () => {
    store[ZOOM_STORAGE_KEY] = '1.2'
    expect(loadZoom()).toBe(1.2)
  })

  it('clamps an out-of-range stored value', () => {
    store[ZOOM_STORAGE_KEY] = '5.0'
    expect(loadZoom()).toBe(ZOOM_MAX)
  })

  it('returns ZOOM_DEFAULT when stored value is not a number', () => {
    store[ZOOM_STORAGE_KEY] = 'bad'
    expect(loadZoom()).toBe(ZOOM_DEFAULT)
  })
})

describe('saveZoom', () => {
  let store: Record<string, string> = {}

  beforeEach(() => {
    store = {}
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => {
        store[key] = value
      },
      removeItem: (key: string) => {
        delete store[key]
      },
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('persists the factor to localStorage', () => {
    saveZoom(1.3)
    expect(store[ZOOM_STORAGE_KEY]).toBe('1.3')
  })

  it('clamps the value before persisting', () => {
    saveZoom(99)
    expect(store[ZOOM_STORAGE_KEY]).toBe(String(ZOOM_MAX))
  })

  it('round-trips through loadZoom', () => {
    saveZoom(0.9)
    expect(loadZoom()).toBe(0.9)
  })
})

describe('applyZoom', () => {
  it('sets the zoom CSS property on the document root', () => {
    applyZoom(1.2)
    expect(document.documentElement.style.zoom).toBe('1.2')
  })

  it('clamps before applying', () => {
    applyZoom(0.1)
    expect(document.documentElement.style.zoom).toBe(String(ZOOM_MIN))
  })

  it('publishes the inverse factor as --app-zoom-inv for vh corrections', () => {
    // CSS `zoom` scales the layout but not vh units, so viewport-sized panes must
    // multiply 100vh by 1/zoom. The inverse is published for calc() multiplication.
    applyZoom(0.8)
    expect(document.documentElement.style.getPropertyValue('--app-zoom-inv')).toBe('1.25')
    applyZoom(1)
    expect(document.documentElement.style.getPropertyValue('--app-zoom-inv')).toBe('1')
    applyZoom(1.2)
    // 1/1.2 rounded to 4 decimals so the style string stays stable
    expect(document.documentElement.style.getPropertyValue('--app-zoom-inv')).toBe('0.8333')
  })
})
