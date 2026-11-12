// Button: the text button primitive (primary / secondary / quiet) with an optional leading icon.
import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'quiet'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  icon?: ReactNode
  /** React 19 passes `ref` through like any prop; pages use it to watch whether a button is on screen. */
  ref?: Ref<HTMLButtonElement>
}

/** A text button. Use one `primary` per view; `secondary` for the rest; `quiet` in dense bars. */
export function Button({ variant = 'secondary', size = 'md', icon, className, children, type, ...rest }: ButtonProps) {
  const classes = ['r-btn', `r-btn--${variant}`, size === 'sm' ? 'r-btn--sm' : '', className ?? '']
    .filter(Boolean)
    .join(' ')
  return (
    <button type={type ?? 'button'} className={classes} {...rest}>
      {icon}
      {children}
    </button>
  )
}
