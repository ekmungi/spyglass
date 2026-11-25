// useSteadyHeight: lets a paged list keep the height of its tallest page, so nothing below it moves.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'

/**
 * Measure an element after each page change and keep the largest height seen, so a shorter page
 * leaves empty space under it instead of pulling everything below it upwards.
 *
 * Put `ref` on the element that holds the page and has no minimum height of its own: it is measured at
 * its natural height, so the stored value is the tallest real page and never grows from its own
 * minimum. Apply the returned `minHeight` to an outer container around it. `dep` is the page index:
 * the element is measured once on mount and after every commit in which `dep` changed. A window resize
 * forgets the stored height, because column widths and line wraps change with the width, and the next
 * layout effect measures again. `minHeight` is undefined until something was measured.
 */
export function useSteadyHeight<T extends HTMLElement>(dep: unknown): { ref: RefObject<T | null>; minHeight: number | undefined } {
  const ref = useRef<T>(null)
  const [minHeight, setMinHeight] = useState<number | undefined>(undefined)
  // Counts resizes, so that the layout effect runs again after one even though the page did not change.
  const [resizes, setResizes] = useState(0)

  useLayoutEffect(() => {
    const height = ref.current?.getBoundingClientRect().height
    if (height === undefined) return
    // Returning the same value when the page is no taller lets React skip the extra render.
    setMinHeight((seen) => (seen === undefined || height > seen ? height : seen))
  }, [dep, resizes])

  useEffect(() => {
    const forget = () => {
      setMinHeight(undefined)
      setResizes((count) => count + 1)
    }
    window.addEventListener('resize', forget)
    return () => window.removeEventListener('resize', forget)
  }, [])

  return { ref, minHeight }
}
