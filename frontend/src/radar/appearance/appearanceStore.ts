// The one appearance store: theme, reading font, interface font and text size. It lives at module
// level so the rail's theme toggle and the Settings controls read and write the same state, it is
// persisted in localStorage, and it is applied to <html> before the first render (initAppearance)
// so the chosen fonts and theme are there from the first paint.
import { readStored, writeStored } from '../hooks/useLocalStorage'
import {
  clampTextWidth,
  DEFAULT_APPEARANCE,
  headingMinWeight,
  TEXT_WIDTH,
  MONO_FONT,
  READING_FONTS,
  TEXT_SIZES,
  UI_FONTS,
  type AppearanceState,
  type FontOption,
  type ThemeChoice,
} from './catalog'

export const STORAGE_KEYS = {
  theme: 'radar.theme',
  readingFont: 'radar.font.reading',
  uiFont: 'radar.font.ui',
  textSize: 'radar.textsize',
  textWidth: 'radar.textwidth',
} as const

const THEMES: readonly ThemeChoice[] = ['system', 'light', 'dark']

/** Font families whose CSS has been requested; a family is fetched once per page load. */
const requested = new Map<string, Promise<unknown>>()

/**
 * Fetch a font's CSS (once). A failed fetch is ignored on purpose: the fallback stack in the
 * font-family list keeps the text readable, so there is nothing the reader needs to do.
 */
export function loadFont(option: FontOption<string>): Promise<unknown> {
  if (!option.load) return Promise.resolve()
  const known = requested.get(option.id)
  if (known) return known
  const pending = option.load().catch(() => undefined)
  requested.set(option.id, pending)
  return pending
}

/** Pick the stored value when it is one of the known ids, otherwise the default. */
function valid<T extends string>(stored: unknown, ids: readonly T[], fallback: T): T {
  return typeof stored === 'string' && (ids as readonly string[]).includes(stored) ? (stored as T) : fallback
}

/** Read the four stored choices; anything missing or unknown (an old or edited value) is the default. */
export function readAppearance(): AppearanceState {
  return {
    theme: valid(readStored<unknown>(STORAGE_KEYS.theme, null), THEMES, DEFAULT_APPEARANCE.theme),
    readingFont: valid(readStored<unknown>(STORAGE_KEYS.readingFont, null), READING_FONTS.map((f) => f.id), DEFAULT_APPEARANCE.readingFont),
    uiFont: valid(readStored<unknown>(STORAGE_KEYS.uiFont, null), UI_FONTS.map((f) => f.id), DEFAULT_APPEARANCE.uiFont),
    textSize: valid(readStored<unknown>(STORAGE_KEYS.textSize, null), TEXT_SIZES.map((s) => s.id), DEFAULT_APPEARANCE.textSize),
    textWidth: clampTextWidth(readStored<unknown>(STORAGE_KEYS.textWidth, null)),
  }
}

/**
 * Write the choices onto the document element: data-theme, --font-serif, --font-sans,
 * --heading-min, --type-scale, --measure and --measure-read. The reading font "sans" reuses the interface stack, so the interface font
 * decides it. Selected fonts are fetched here; the stack keeps text readable until they arrive.
 */
export function applyAppearance(state: AppearanceState): void {
  const root = document.documentElement
  if (state.theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', state.theme)

  const ui = UI_FONTS.find((f) => f.id === state.uiFont) ?? UI_FONTS[0]
  const reading = READING_FONTS.find((f) => f.id === state.readingFont) ?? READING_FONTS[0]
  const size = TEXT_SIZES.find((s) => s.id === state.textSize) ?? TEXT_SIZES[0]
  root.style.setProperty('--font-sans', ui.stack)
  root.style.setProperty('--font-serif', reading.id === 'sans' ? ui.stack : reading.stack)
  root.style.setProperty('--heading-min', String(headingMinWeight(reading.id)))
  root.style.setProperty('--type-scale', String(size.scale))
  root.style.setProperty('--measure', `${state.textWidth}px`)
  root.style.setProperty('--measure-read', `${state.textWidth + TEXT_WIDTH.readerExtra}px`)
  void loadFont(ui)
  void loadFont(reading)
  void loadFont(MONO_FONT)
}

let current: AppearanceState = readAppearance()
const listeners = new Set<() => void>()

/** The current choices (a stable object until something changes, as useSyncExternalStore needs). */
export function getAppearance(): AppearanceState {
  return current
}

/** Subscribe to changes; returns the unsubscribe function. */
export function subscribeAppearance(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Read the stored choices, apply them, and tell subscribers. Call once before the first render. */
export function initAppearance(): void {
  current = readAppearance()
  applyAppearance(current)
  listeners.forEach((listener) => listener())
}

/** Change some choices: remember them, apply them at once and tell subscribers. */
export function setAppearance(patch: Partial<AppearanceState>): void {
  const next: AppearanceState = { ...current, ...patch }
  for (const key of Object.keys(patch) as Array<keyof AppearanceState>) writeStored(STORAGE_KEYS[key], next[key])
  current = next
  applyAppearance(next)
  listeners.forEach((listener) => listener())
}

/** Move the text width by `delta` px (negative narrows), staying inside the allowed range. */
export function stepTextWidth(delta: number): void {
  setAppearance({ textWidth: clampTextWidth(current.textWidth + delta) })
}

/** Put every choice back to the default (including the theme). */
export function resetAppearance(): void {
  setAppearance({ ...DEFAULT_APPEARANCE })
}
