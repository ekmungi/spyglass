// Rule: the hairline divider that replaces boxes throughout the interface.

export interface RuleProps {
  spacing?: 'sm' | 'md' | 'lg'
  strong?: boolean
}

/** A hairline `<hr>`; `spacing` sets the vertical margin, `strong` darkens the line. */
export function Rule({ spacing = 'md', strong = false }: RuleProps) {
  const classes = ['r-rule', spacing !== 'md' ? `r-rule--${spacing}` : '', strong ? 'r-rule--strong' : '']
    .filter(Boolean)
    .join(' ')
  return <hr className={classes} />
}
