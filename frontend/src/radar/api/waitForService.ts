// waitForService: polls GET /api/health until the service answers, for the moment after Spyglass
// has been asked to restart itself on another data folder.
import { rootFetch } from './transport'

/** How long to wait for the service, in milliseconds. A start on a new folder takes 10 to 40 seconds. */
const DEFAULT_TIMEOUT_MS = 60_000
/** The time between two health checks. */
const DEFAULT_INTERVAL_MS = 1000
/** How long to look for the old service going quiet before an answer is trusted anyway. */
const DEFAULT_STOP_GRACE_MS = 10_000
/** A health check that has not answered after this long counts as no answer. */
const CHECK_TIMEOUT_MS = 5000

export interface WaitForServiceOptions {
  timeoutMs?: number
  intervalMs?: number
  /**
   * True when the service was just told to stop: the old copy still answers for a moment, so an answer
   * counts only after one check has failed, or after stopGraceMs when the stop was never seen.
   */
  afterStop?: boolean
  stopGraceMs?: number
}

/** One health check: true when /api/health answers 200 in time, false for anything else. */
async function healthAnswers(): Promise<boolean> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), CHECK_TIMEOUT_MS)
  try {
    const response = await rootFetch('/api/health', { signal: controller.signal })
    return response.status === 200
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/** Poll /api/health once a second; true as soon as it answers 200, false after the time limit. */
export async function waitForService(options: WaitForServiceOptions = {}): Promise<boolean> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, intervalMs = DEFAULT_INTERVAL_MS, afterStop = false, stopGraceMs = DEFAULT_STOP_GRACE_MS } = options
  const startedAt = Date.now()
  let sawStop = !afterStop
  while (Date.now() - startedAt < timeoutMs) {
    const up = await healthAnswers()
    if (!up) sawStop = true
    else if (sawStop || Date.now() - startedAt >= stopGraceMs) return true
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return false
}
