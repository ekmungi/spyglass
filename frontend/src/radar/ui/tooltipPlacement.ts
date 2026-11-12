// Tooltip placement: slide a tooltip bubble sideways so it stays inside the nearest area that clips
// overflow (the page column, a dialog), keeping a tip at a row's right end readable.

// Space kept between the bubble and the clipping edge, in px.
const EDGE_GAP = 6

/** The horizontal extent of the nearest ancestor that clips overflow, or the window. */
function clipBounds(element: HTMLElement): { left: number; right: number } {
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (getComputedStyle(node).overflowX !== 'visible') {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.left + node.clientWidth }
    }
  }
  return { left: 0, right: window.innerWidth }
}

/**
 * Measure `bubble` and write the slide that keeps it inside its clipping area to --tip-dx, which
 * the stylesheet adds to the centring transform. Returns the slide in px (0 when it fits).
 */
export function placeBubble(bubble: HTMLElement): number {
  bubble.style.setProperty('--tip-dx', '0px')
  const rect = bubble.getBoundingClientRect()
  const bounds = clipBounds(bubble)
  let dx = 0
  if (rect.right > bounds.right - EDGE_GAP) dx = bounds.right - EDGE_GAP - rect.right
  if (rect.left + dx < bounds.left + EDGE_GAP) dx = bounds.left + EDGE_GAP - rect.left
  const rounded = Math.round(dx)
  bubble.style.setProperty('--tip-dx', `${rounded}px`)
  return rounded
}
