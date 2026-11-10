// Appearance state: workspace layout variables + localStorage persistence for
// theme, font sizes, and widths, so slider choices survive reloads.
import {
  applyPreset,
  applySizes,
  buildPresets,
  DEFAULT_SIZES,
  type Sizes,
} from './presets'

export interface Layout {
  // Centered workspace column width in px (the mockup .wrap, user-adjustable).
  maxWidth: number
  // List pane share of the two-pane split, in percent of the row.
  listWidth: number
}

export const DEFAULT_LAYOUT: Layout = { maxWidth: 1180, listWidth: 39 }

export interface Appearance {
  theme: string
  sizes: Sizes
  layout: Layout
}

const STORAGE_KEY = 'spyglass-appearance'

const DEFAULT_APPEARANCE: Appearance = {
  theme: 'anthropic-coral-classic',
  sizes: DEFAULT_SIZES,
  layout: DEFAULT_LAYOUT,
}

/** Apply the layout widths as CSS variables (live, like the font sliders). */
export function applyLayout(layout: Layout): void {
  const root = document.documentElement
  root.style.setProperty('--layout-max-width', `${layout.maxWidth}px`)
  root.style.setProperty('--list-pane-width', `${layout.listWidth}%`)
}

/** Persist the full appearance so sliders survive reloads. */
export function saveAppearance(appearance: Appearance): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance))
  } catch {
    // Storage unavailable (private mode etc.); appearance stays session-only.
  }
}

/** Stored appearance merged over the defaults; corrupt entries fall back. */
export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return DEFAULT_APPEARANCE
    }
    const stored = JSON.parse(raw) as Partial<Appearance>
    return {
      theme: stored.theme ?? DEFAULT_APPEARANCE.theme,
      sizes: { ...DEFAULT_SIZES, ...stored.sizes },
      layout: { ...DEFAULT_LAYOUT, ...stored.layout },
    }
  } catch {
    return DEFAULT_APPEARANCE
  }
}

/** Apply the stored theme, sizes, and layout on startup. */
export function applyStoredAppearance(): void {
  const appearance = loadAppearance()
  const preset = buildPresets().find((p) => p.name === appearance.theme)
  if (preset) {
    applyPreset(preset)
  }
  applySizes(appearance.sizes)
  applyLayout(appearance.layout)
}
