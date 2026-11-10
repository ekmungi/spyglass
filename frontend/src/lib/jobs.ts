// Words for background jobs: what the reader says while Claude prepares or files a note.
import type { ClaudeJob } from './types'

export const JOB_ACTIVE = new Set(['queued', 'running'])

export function isActive(job: ClaudeJob | undefined | null): boolean {
  return !!job && JOB_ACTIVE.has(job.status)
}

/** The status line for a job in progress. */
export function activeLine(job: ClaudeJob): string {
  const what = job.kind === 'prepare-detail' ? 'Preparing the detailed note' : 'Filing the note'
  // A queued job with progress is waiting for the user's Claude usage limit to reset.
  if (job.status === 'queued' && job.progress) return `${what}: ${job.progress.charAt(0).toLowerCase()}${job.progress.slice(1)}`
  if (job.status === 'queued') return `${what}: waiting for the job before it`
  return job.progress && job.progress !== 'Claude is working' ? `${what}: ${job.progress.charAt(0).toLowerCase()}${job.progress.slice(1)}` : `${what} in the background`
}

/** The line shown after a job failed. */
export function failedLine(job: ClaudeJob): string {
  const what = job.kind === 'prepare-detail' ? "Couldn't prepare the note" : "Couldn't file the note"
  return `${what}: ${job.error ?? 'no reason given'}`
}

/** The folder of a vault-relative note path ("02 AREAS/Imaging/x.md" -> "02 AREAS/Imaging"). */
export function folderOf(path: string): string {
  const cut = path.lastIndexOf('/')
  return cut > 0 ? path.slice(0, cut) : 'the vault root'
}

/** How much of the user's Claude limits a finished job reported, e.g.
 * "Claude usage after this: 5-hour 50%, week 21% (claude-sonnet-5-5)". Null when not reported. */
export function usageLine(job: ClaudeJob): string | null {
  const five = job.usage_five_hour
  const week = job.usage_week
  if (five == null && week == null) return null
  const parts = [
    five != null ? `5-hour ${Math.round(five * 100)}%` : null,
    week != null ? `week ${Math.round(week * 100)}%` : null,
  ].filter(Boolean)
  return `Claude usage after this: ${parts.join(', ')}${job.model ? ` (${job.model})` : ''}`
}
