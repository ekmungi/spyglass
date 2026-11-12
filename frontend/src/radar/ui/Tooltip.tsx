// Tooltip: a small label shown on hover and keyboard focus of its child (CSS-driven, no portal).
// Just before it can show, the bubble is measured and slid sideways if it would run past the edge
// of the area that clips it (the page column, a dialog), so a tip at a row's right end stays readable.
import { useRef, type ReactNode } from 'react'
import { placeBubble } from './tooltipPlacement'

export type TooltipSide = 'top' | 'bottom' | 'right'

export interface TooltipProps {
  label: string
  side?: TooltipSide
  children: ReactNode
}

/** Wrap a control to show `label` above (or beside) it on hover/focus; purely visual (aria-hidden). */
export function Tooltip({ label, side = 'top', children }: TooltipProps) {
  const bubbleRef = useRef<HTMLSpanElement>(null)
  // Side tips (the rail) open into free space; only tips above or below need the edge check.
  const place = () => {
    if (side !== 'right' && bubbleRef.current) placeBubble(bubbleRef.current)
  }
  return (
    <span className={`r-tip${side === 'top' ? '' : ` r-tip--${side}`}`} onPointerEnter={place} onFocus={place}>
      {children}
      <span className="r-tip__bubble" aria-hidden="true" ref={bubbleRef}>
        {label}
      </span>
    </span>
  )
}
