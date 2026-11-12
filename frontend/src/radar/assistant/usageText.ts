// usageText: the words for token figures. "Read 12,400 tokens, 91% from cache · wrote 380".
import type { UsageFigures } from '../api/usageTypes'

const NUMBER = new Intl.NumberFormat('en-US')

/** A count with thousands separators. */
export function formatCount(value: number): string {
  return NUMBER.format(Math.round(value))
}

/** A share (0 to 1) as a whole percentage; anything under 1% that is not zero reads "under 1%". */
export function formatShare(share: number): string {
  const percent = share * 100
  return percent > 0 && percent < 1 ? 'under 1%' : `${Math.round(percent)}%`
}

/**
 * One quiet line about an answer: the model, what the model read (the whole prompt, and how much of
 * it came from the provider's cache) and how much it wrote. Parts that were not reported are left out.
 */
export function describeUsage(figures: UsageFigures): string {
  const parts: string[] = []
  if (figures.model) parts.push(figures.model)
  if (figures.context_tokens !== undefined) {
    const cached = figures.cached_share !== undefined ? `, ${formatShare(figures.cached_share)} from cache` : ''
    parts.push(`Read ${formatCount(figures.context_tokens)} tokens${cached}`)
  }
  if (figures.output_tokens !== undefined) parts.push(`wrote ${formatCount(figures.output_tokens)}`)
  return parts.join(' · ')
}

export const CONDENSED_NOTE = 'Earlier messages were condensed to save usage.'
