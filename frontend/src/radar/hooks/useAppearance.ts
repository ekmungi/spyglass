// useAppearance: the reading font, interface font and text size, shared with every other user of
// the appearance store. Each setter applies at once and is remembered on this device.
import { useCallback, useSyncExternalStore } from 'react'
import { getAppearance, resetAppearance, setAppearance, stepTextWidth, subscribeAppearance } from '../appearance/appearanceStore'
import { clampTextWidth, type AppearanceState, type ReadingFontId, type TextSizeId, type UiFontId } from '../appearance/catalog'

export interface AppearanceApi {
  appearance: AppearanceState
  setReadingFont: (id: ReadingFontId) => void
  setUiFont: (id: UiFontId) => void
  setTextSize: (id: TextSizeId) => void
  /** Set the centre column width in px (kept inside the allowed range). */
  setTextWidth: (px: number) => void
  /** Step the width by a signed number of px; the reader's More menu uses this. */
  stepWidth: (delta: number) => void
  /** Back to the defaults for every appearance choice, theme included. */
  reset: () => void
}

/** The current appearance choices and their setters. */
export function useAppearance(): AppearanceApi {
  const appearance = useSyncExternalStore(subscribeAppearance, getAppearance)
  const setReadingFont = useCallback((readingFont: ReadingFontId) => setAppearance({ readingFont }), [])
  const setUiFont = useCallback((uiFont: UiFontId) => setAppearance({ uiFont }), [])
  const setTextSize = useCallback((textSize: TextSizeId) => setAppearance({ textSize }), [])
  const setTextWidth = useCallback((textWidth: number) => setAppearance({ textWidth: clampTextWidth(textWidth) }), [])
  return { appearance, setReadingFont, setUiFont, setTextSize, setTextWidth, stepWidth: stepTextWidth, reset: resetAppearance }
}
