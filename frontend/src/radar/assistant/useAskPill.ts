// useAskPill: decides when the Ask pill shows. It watches the page's own Ask button with an
// IntersectionObserver; the pill shows when that button is out of view, the panel is closed and
// the page is the one on screen. Without IntersectionObserver the pill never shows.
import { useCallback, useEffect, useState } from 'react'
import { useAssistState, type Surface } from './assistStore'

/** The pill's decision: shown when the page's own Ask button is out of view and the panel is closed. */
export function pillVisible(buttonOutOfView: boolean, panelOpen: boolean, pageActive: boolean): boolean {
  return buttonOutOfView && !panelOpen && pageActive
}

/**
 * Watch the page's own Ask button. Returns a ref callback for that button and whether the pill
 * should show. Without IntersectionObserver the pill never shows (the button is all there is).
 */
export function useAskPill(surface: Surface, active: boolean): { watchButton: (element: HTMLElement | null) => void; shown: boolean } {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const [outOfView, setOutOfView] = useState(false)
  const panelOpen = useAssistState().open[surface]
  const watchButton = useCallback((next: HTMLElement | null) => setElement(next), [])

  useEffect(() => {
    if (!element || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => {
      const latest = entries[entries.length - 1]
      if (latest) setOutOfView(!latest.isIntersecting)
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      setOutOfView(false)
    }
  }, [element])

  return { watchButton, shown: pillVisible(outOfView, panelOpen, active) }
}
