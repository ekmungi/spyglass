// Chip: a rounded toggle used for filters (section chips, Saved, From you).
import type { ButtonHTMLAttributes } from 'react'

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean
  count?: number
}

/** A toggle filter chip; `selected` sets aria-pressed and the accent fill; `count` adds a number. */
export function Chip({ selected = false, count, className, children, type, ...rest }: ChipProps) {
  return (
    <button
      type={type ?? 'button'}
      aria-pressed={selected}
      className={['r-chip', className ?? ''].filter(Boolean).join(' ')}
      {...rest}
    >
      {children}
      {count !== undefined && <span className="r-chip__count">{count}</span>}
    </button>
  )
}
