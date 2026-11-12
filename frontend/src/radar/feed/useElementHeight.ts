// useElementHeight: the rendered height of an element, kept current as it wraps or resizes. The Feed
// uses it to park the sticky date heading exactly under its sticky filter bar, whose height changes
// when the controls wrap onto a second line.
import { useLayoutEffect, useState, type RefObject } from 'react'

/** The element's height in pixels (0 until measured, and always 0 where ResizeObserver is missing). */
export function useElementHeight(ref: RefObject<HTMLElement | null>): number {
  const [height, setHeight] = useState(0)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const measure = () => setHeight(Math.round(element.getBoundingClientRect().height))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return height
}
