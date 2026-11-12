// Motion helpers: read the duration tokens from tokens.css at run time, so scripts that time an
// exit (usePresence, the toast stack) follow the same numbers as the stylesheets, including zero
// under reduced motion.

/** The duration tokens defined in tokens.css. */
export type DurationToken = '--dur-fast' | '--dur' | '--dur-slow'

/** True when the person has asked the system for reduced motion. */
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Parse a CSS time ("200ms", "0.28s") into milliseconds; anything unreadable or negative is 0. */
export function parseDurationMs(value: string): number {
  const match = /^\s*(\d*\.?\d+)(ms|s)\s*$/.exec(value)
  if (!match) return 0
  const amount = Number(match[1])
  return match[2] === 's' ? Math.round(amount * 1000) : amount
}

/**
 * The current value of a duration token in milliseconds. It is 0 when the styles are not loaded
 * (tests) or under reduced motion, so callers can treat 0 as "no animation: act at once".
 */
export function motionMs(token: DurationToken): number {
  if (typeof document === 'undefined' || prefersReducedMotion()) return 0
  return parseDurationMs(getComputedStyle(document.documentElement).getPropertyValue(token))
}

/** The current value of a CSS custom property on the root (an easing curve for script animations). */
export function motionToken(name: '--ease-enter' | '--ease-exit'): string {
  if (typeof document === 'undefined') return 'ease-out'
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || 'ease-out'
}
