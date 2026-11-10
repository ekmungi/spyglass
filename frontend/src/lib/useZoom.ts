// useZoom: app-level CSS zoom persisted to localStorage so it survives reloads.
//
// The web app runs in a Chromium-based Obsidian window that honours the CSS
// `zoom` property on the root element, making this a simple and reliable way
// to let the user scale the entire UI without touching the native browser zoom
// (which we cannot read or control from JS).

/** localStorage key for the persisted zoom factor. */
export const ZOOM_STORAGE_KEY = 'spyglass:zoom'

/** Minimum zoom factor (70%). */
export const ZOOM_MIN = 0.7

/** Maximum zoom factor (150%). */
export const ZOOM_MAX = 1.5

/** Step size for increment/decrement (10%). */
export const ZOOM_STEP = 0.1

/** Default zoom factor (100% – no scaling). */
export const ZOOM_DEFAULT = 1.0

/**
 * Read the stored zoom factor from localStorage, clamped to [ZOOM_MIN, ZOOM_MAX].
 * Falls back to ZOOM_DEFAULT when the stored value is absent or unparseable.
 *
 * @returns The persisted zoom factor as a number in [ZOOM_MIN, ZOOM_MAX].
 */
export function loadZoom(): number {
  try {
    const raw = localStorage.getItem(ZOOM_STORAGE_KEY)
    if (raw === null) return ZOOM_DEFAULT
    const parsed = parseFloat(raw)
    if (isNaN(parsed)) return ZOOM_DEFAULT
    return clampZoom(parsed)
  } catch {
    // localStorage unavailable (private mode etc.).
    return ZOOM_DEFAULT
  }
}

/**
 * Persist the zoom factor to localStorage.
 *
 * @param factor - The zoom factor to store.  Values outside [ZOOM_MIN, ZOOM_MAX]
 *                 are clamped before storing.
 */
export function saveZoom(factor: number): void {
  try {
    localStorage.setItem(ZOOM_STORAGE_KEY, String(clampZoom(factor)))
  } catch {
    // Storage unavailable; setting stays session-only.
  }
}

/**
 * Apply the zoom factor to the document root via the CSS `zoom` property.
 * A value of 1.0 is written as '1' so Chromium applies no scaling.
 *
 * Also publishes `--app-zoom-inv` (1/factor, 4 decimals): CSS `zoom` scales the
 * layout but NOT viewport units, so any pane sized with 100vh must multiply by the
 * inverse to stay inside the visible viewport.
 *
 * @param factor - The zoom factor to apply.
 */
export function applyZoom(factor: number): void {
  const clamped = clampZoom(factor)
  document.documentElement.style.zoom = String(clamped)
  const inverse = Math.round((1 / clamped) * 10000) / 10000
  document.documentElement.style.setProperty('--app-zoom-inv', String(inverse))
}

/**
 * Clamp a zoom factor to the valid [ZOOM_MIN, ZOOM_MAX] range, rounded to one
 * decimal place to avoid floating-point accumulation (0.1 + 0.2 ≠ 0.3).
 *
 * @param factor - The zoom factor to clamp.
 * @returns The clamped, rounded value.
 */
export function clampZoom(factor: number): number {
  const rounded = Math.round(factor * 10) / 10
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, rounded))
}

/**
 * Apply the stored zoom on app startup so the first paint uses the user's
 * preference without a visible re-layout flash.
 */
export function applyStoredZoom(): void {
  applyZoom(loadZoom())
}
