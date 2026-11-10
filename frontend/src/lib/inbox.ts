// Inbox helpers shared by the Inbox tab and its tests (kept out of the component file so
// React fast refresh can treat InboxTab.tsx as components only).
import { formatAge } from './dates'
import type { InboxRunInfo } from './types'

// Works without the spyglass-inbox skill installed: inbox_start returns the instructions.
export const INBOX_PROMPT =
  'Process my Spyglass inbox: call the spyglass tool inbox_start first and follow the instructions it returns.'

/** One line on the latest run: running, done with a count, or failed with its reason. */
export function runLine(run: InboxRunInfo | null): string {
  if (!run) return 'Not processed yet.'
  if (run.status === 'running') return `Processing (started ${formatAge(run.started_at)})...`
  const when = formatAge(run.finished_at ?? run.started_at)
  if (run.status === 'ok') return `Last run ${when}: ${run.papers} paper${run.papers === 1 ? '' : 's'}.`
  return `Last run ${when} failed: ${run.error ?? 'no reason given'}`
}
