// ZoomControl: a compact "− 100% +" cluster that lets the user scale the entire
// dashboard.  Zoom is applied via CSS `zoom` on the document root (Chromium
// honours this in the Obsidian web view) and persisted to localStorage so the
// preference survives reloads.
import { useState } from 'react'
import { applyZoom, loadZoom, saveZoom, ZOOM_DEFAULT, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP } from '../lib/useZoom'

/**
 * Tiny zoom cluster rendered in the app header.
 *
 * The component is intentionally self-contained: it reads the stored value on
 * mount and persists every change, so the caller need not manage any state.
 */
export function ZoomControl() {
  const [zoom, setZoom] = useState<number>(() => {
    // Read stored preference on mount so the displayed value matches what was
    // just applied by applyStoredZoom() in main.tsx.
    return loadZoom()
  })

  /** Apply, persist, and update state for a new zoom factor. */
  const apply = (next: number) => {
    applyZoom(next)
    saveZoom(next)
    setZoom(next)
  }

  const decrement = () => apply(zoom - ZOOM_STEP)
  const increment = () => apply(zoom + ZOOM_STEP)
  const reset = () => apply(ZOOM_DEFAULT)

  const pct = Math.round(zoom * 100)

  // Base button style matching the WorkspaceBar pill style.
  const btn =
    'border border-border px-1.5 py-0.5 hover:border-accent hover:text-ink disabled:opacity-40'

  return (
    <div
      className="flex items-center gap-0.5 text-muted"
      style={{ fontSize: 'var(--font-size-actions)' }}
      aria-label="Zoom"
    >
      <button
        type="button"
        aria-label="Zoom out"
        title="Zoom out"
        className={btn}
        style={{ borderRadius: 'var(--radius-control) 0 0 var(--radius-control)' }}
        onClick={decrement}
        disabled={zoom <= ZOOM_MIN}
      >
        −
      </button>
      <button
        type="button"
        aria-label={`Zoom reset (current: ${pct}%)`}
        title="Reset zoom to 100%"
        className={`${btn} min-w-[2.8rem] text-center`}
        style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}
        onClick={reset}
      >
        {pct}%
      </button>
      <button
        type="button"
        aria-label="Zoom in"
        title="Zoom in"
        className={btn}
        style={{ borderRadius: '0 var(--radius-control) var(--radius-control) 0' }}
        onClick={increment}
        disabled={zoom >= ZOOM_MAX}
      >
        +
      </button>
    </div>
  )
}
