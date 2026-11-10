// Background auto-refresh scheduler and status text formatter.
// AutoRefresher is a pure, injectable class: no Obsidian imports, testable with fake deps.

/** Injectable dependencies for AutoRefresher. */
export interface AutoRefreshDeps {
  /** Returns true when /api/health answers 200. */
  isHealthy: () => Promise<boolean>
  /** POSTs /api/refresh (collection only, no LLM). Returns true on HTTP 200. */
  refresh: () => Promise<boolean>
  /** Called after each successful refresh with the timestamp in ms. */
  onRefreshed: (atMs: number) => void
  /** Injectable clock so tests can control time without real timers. */
  now: () => number
}

/** Manages cadence, backoff, and in-flight guard for background data collection refreshes. */
export class AutoRefresher {
  private deps: AutoRefreshDeps
  private intervalMs: number
  private maxBackoffMs: number
  private inFlight = false
  private failures = 0
  private nextAllowed = 0

  constructor(deps: AutoRefreshDeps, intervalMs: number, maxBackoffMs = 6 * 60 * 60 * 1000) {
    this.deps = deps
    this.intervalMs = intervalMs
    this.maxBackoffMs = maxBackoffMs
  }

  /** One scheduler tick: honours in-flight guard, backoff, health, and failure accounting.
   *  Returns 'skipped' | 'unhealthy' | 'refreshed' | 'failed'. */
  async tick(): Promise<'skipped' | 'unhealthy' | 'refreshed' | 'failed'> {
    if (this.inFlight) {
      return 'skipped'
    }
    if (this.deps.now() < this.nextAllowed) {
      return 'skipped'
    }
    this.inFlight = true
    try {
      if (!(await this.deps.isHealthy())) {
        return 'unhealthy'
      }
      const ok = await this.deps.refresh()
      if (ok) {
        this.failures = 0
        this.nextAllowed = 0
        this.deps.onRefreshed(this.deps.now())
        return 'refreshed'
      }
      this.failures++
      this.nextAllowed =
        this.deps.now() + Math.min(this.intervalMs * Math.pow(2, this.failures), this.maxBackoffMs)
      return 'failed'
    } catch {
      this.failures++
      this.nextAllowed =
        this.deps.now() + Math.min(this.intervalMs * Math.pow(2, this.failures), this.maxBackoffMs)
      return 'failed'
    } finally {
      this.inFlight = false
    }
  }

  /** Force a refresh bypassing the backoff window (e.g. "Refresh now" command).
   *  Still respects the in-flight guard. */
  async forceTick(): Promise<'skipped' | 'unhealthy' | 'refreshed' | 'failed'> {
    if (this.inFlight) {
      return 'skipped'
    }
    // Temporarily clear the backoff so tick() proceeds
    const savedNextAllowed = this.nextAllowed
    this.nextAllowed = 0
    const result = await this.tick()
    // Restore backoff only if the forced tick itself failed (tick() already updated nextAllowed)
    if (result !== 'refreshed' && result !== 'failed') {
      this.nextAllowed = savedNextAllowed
    }
    return result
  }
}

// ---------------------------------------------------------------------------
// Status text
// ---------------------------------------------------------------------------

/** Pure formatter for the status bar text.
 *  @param lastAtMs - timestamp (ms) of the last successful refresh, or null
 *  @param nowMs    - current time (ms) for computing the elapsed duration
 */
export function formatLastRefreshed(lastAtMs: number | null, nowMs: number): string {
  if (lastAtMs === null) {
    return 'Spyglass: never refreshed'
  }
  const elapsedMs = nowMs - lastAtMs
  const elapsedSec = Math.floor(elapsedMs / 1000)
  if (elapsedSec < 60) {
    return 'Spyglass: refreshed just now'
  }
  const elapsedMin = Math.floor(elapsedSec / 60)
  if (elapsedMin < 60) {
    return `Spyglass: refreshed ${elapsedMin}m ago`
  }
  const elapsedHr = Math.floor(elapsedMin / 60)
  return `Spyglass: refreshed ${elapsedHr}h ago`
}

/** Whether the service is healthy enough to AUTO-REFRESH against: up (HTTP 200) AND its DB passed
 *  the startup integrity check. A degraded DB still answers 200 (so the dashboard can load and show
 *  the problem), but auto-refresh must skip it -- writing to or VACUUM-INTO-backing a malformed DB
 *  makes things worse. The service also refuses /api/refresh with 409 when degraded. */
export function healthyForRefresh(status: number, body: { db?: string } | null): boolean {
  return status === 200 && body?.db === 'ok'
}
