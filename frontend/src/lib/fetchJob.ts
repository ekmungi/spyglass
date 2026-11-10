// Fetch-job status helpers: the single place the UI decides "is this still going to happen?"
// Mirrors ACTIVE_STATUSES in the service's fetch_queue.py.
import type { FetchJobState } from './types'

// A job is active while it still intends to do work, terminal once it cannot. Every
// poll loop in the dashboard starts and stops on this distinction.
export const ACTIVE_JOB_STATUSES: readonly FetchJobState['status'][] = ['queued', 'running']

/** Whether a fetch job is still going to run; false for terminal jobs and for no job at all.
 *
 * @param job The card's most recent fetch job, or null/undefined when it has never been
 *            fetched (or the service predates fetch jobs and sends no job at all).
 * @returns True while the job is queued or running.
 */
export function isJobActive(job: FetchJobState | null | undefined): boolean {
  return job != null && ACTIVE_JOB_STATUSES.includes(job.status)
}
