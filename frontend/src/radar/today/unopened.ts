// unopened: how the line about never-opened briefs names its dates.
import { parseDay } from '../lib/format'

const LOCALE = 'en-GB'

export interface UnopenedPart {
  day: string
  /** "10" when the next date is in the same month, otherwise "11 November". */
  text: string
}

/** The dates in the order they happened, each with the text that names it in the sentence. */
export function unopenedParts(days: string[]): UnopenedPart[] {
  const ordered = [...new Set(days)].sort()
  return ordered.map((day, index) => {
    const date = parseDay(day)
    const next = ordered[index + 1] ? parseDay(ordered[index + 1]) : null
    const sameMonth = next !== null && next.getMonth() === date.getMonth() && next.getFullYear() === date.getFullYear()
    return { day, text: sameMonth ? String(date.getDate()) : `${date.getDate()} ${date.toLocaleDateString(LOCALE, { month: 'long' })}` }
  })
}
