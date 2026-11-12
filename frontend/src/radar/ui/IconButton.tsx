// IconButton: an icon-only button whose label is both its accessible name and its tooltip.
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Tooltip, type TooltipSide } from './Tooltip'

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  label: string
  icon: ReactNode
  pressed?: boolean
  size?: 'sm' | 'md'
  tooltip?: boolean
  tooltipSide?: TooltipSide
}

/** An icon-only button; `pressed` renders a toggle (aria-pressed), `tooltip={false}` hides the tip. */
export function IconButton({
  label,
  icon,
  pressed,
  size = 'md',
  tooltip = true,
  tooltipSide = 'top',
  className,
  type,
  ...rest
}: IconButtonProps) {
  const button = (
    <button
      type={type ?? 'button'}
      aria-label={label}
      aria-pressed={pressed === undefined ? undefined : pressed}
      className={['r-iconbtn', size === 'sm' ? 'r-iconbtn--sm' : '', className ?? ''].filter(Boolean).join(' ')}
      {...rest}
    >
      {icon}
    </button>
  )
  return tooltip ? (
    <Tooltip label={label} side={tooltipSide}>
      {button}
    </Tooltip>
  ) : (
    button
  )
}
