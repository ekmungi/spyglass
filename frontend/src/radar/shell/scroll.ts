// Scroll restoration for the main column: re-applies a remembered offset while late content
// (loaded data, images) grows the page, then stops.

const SETTLE_MS = 1500

/**
 * Scroll `element` to `top`. If the content is not yet tall enough, keep re-applying on resize
 * until it is or until 1.5 s pass, then give up quietly. Returns a cancel function.
 */
export function restoreScroll(element: HTMLElement, top: number): () => void {
  element.scrollTop = top
  if (top <= 0 || typeof ResizeObserver === 'undefined') return () => undefined
  const content = element.firstElementChild
  if (!content) return () => undefined
  const observer = new ResizeObserver(() => {
    element.scrollTop = top
    if (Math.abs(element.scrollTop - top) < 2) observer.disconnect()
  })
  observer.observe(content)
  const timer = setTimeout(() => observer.disconnect(), SETTLE_MS)
  return () => {
    clearTimeout(timer)
    observer.disconnect()
  }
}
