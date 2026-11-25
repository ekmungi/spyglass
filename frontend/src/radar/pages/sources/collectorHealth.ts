// The alert marks for the Searches and the FDA decisions tabs. The rule that marks a row "Failing" (its
// status reads as a problem) marks its tab too, so a source that is only not set up gets no mark.
import type { CollectorRow } from './api'
import { collectorStatus } from './describe'
import { signalRows } from './signalRows'

/** Whether a collector's row reads "Failing". */
function isFailing(row: CollectorRow): boolean {
  return collectorStatus(row).tone === 'problem'
}

/** The alert text for the Searches tab ("1 search is failing"), or undefined when no search fails. */
export function failingSearchesAlert(collectors: readonly CollectorRow[]): string | undefined {
  const count = signalRows(collectors).filter(isFailing).length
  if (count === 0) return undefined
  return count === 1 ? '1 search is failing' : `${count} searches are failing`
}

/** The alert text for the FDA decisions tab, or undefined when the FDA check is not failing. */
export function fdaAlert(collectors: readonly CollectorRow[]): string | undefined {
  const row = collectors.find((entry) => entry.key === 'fda')
  return row && isFailing(row) ? 'The FDA check is failing' : undefined
}
