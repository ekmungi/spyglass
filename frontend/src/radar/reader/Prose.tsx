// Prose: injects the server-sanitized reader HTML into the typographic container, then wraps
// tables for horizontal scrolling, opens outside links in a new tab and lazy-loads images.
import { forwardRef, memo, useEffect, useImperativeHandle, useMemo, useRef } from 'react'
import { enhanceProse } from './enhanceProse'

/**
 * The reading container; `html` must already be sanitized (the server does this). Memoised, with
 * a stable innerHTML object, so a parent re-render never rewrites the document: that would undo
 * the enhancements above and drop the reader's text selection.
 */
export const Prose = memo(
  forwardRef<HTMLDivElement, { html: string }>(function Prose({ html }, ref) {
    const innerRef = useRef<HTMLDivElement>(null)
    useImperativeHandle(ref, () => innerRef.current as HTMLDivElement)
    const markup = useMemo(() => ({ __html: html }), [html])
    useEffect(() => {
      if (innerRef.current) enhanceProse(innerRef.current)
    }, [markup])
    return <div ref={innerRef} className="r-prose" dangerouslySetInnerHTML={markup} />
  }),
)
