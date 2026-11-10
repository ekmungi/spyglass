// Service supervisor: start if needed, poll health, stop gracefully or hard.

export type EnsureResult = 'already-running' | 'started' | 'failed'

export interface ServiceDeps {
  repoPath: string
  port: number
  /** Returns true when /api/health answers ok. */
  fetchHealthy: () => Promise<boolean>
  /** Starts the child process and returns its pid. */
  spawnFn: () => { pid: number }
  /** POSTs /api/shutdown; resolves true when the service stopped in time. */
  shutdownFn: () => Promise<boolean>
  /** Hard fallback: kill the process tree (taskkill /T /F on Windows). */
  killFn: (pid: number) => void
  pollMs: number
  timeoutMs: number
}

/** Supervises the Python service from the plugin (connect-only when possible). */
export class ServiceManager {
  private deps: ServiceDeps
  private pid: number | null = null

  constructor(deps: ServiceDeps) {
    this.deps = deps
  }

  /** Make sure a healthy service exists: reuse a running one, else spawn and wait. */
  async ensureRunning(): Promise<EnsureResult> {
    if (await this.deps.fetchHealthy()) {
      return 'already-running'
    }
    const child = this.deps.spawnFn()
    this.pid = child.pid
    const deadline = Date.now() + this.deps.timeoutMs
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, this.deps.pollMs))
      if (await this.deps.fetchHealthy()) {
        return 'started'
      }
    }
    return 'failed'
  }

  /** Stop the service we spawned: graceful HTTP shutdown, then the hard kill. */
  async stop(): Promise<void> {
    if (this.pid === null) {
      return
    }
    const stopped = await this.deps.shutdownFn()
    if (!stopped) {
      this.deps.killFn(this.pid)
    }
    this.pid = null
  }

  /** Restart the service to load fresh code (e.g. after a repo update).
   *
   * Stops the currently-running instance via its HTTP shutdown endpoint -- which works even
   * when THIS plugin session did not spawn it (a previous session did, so we hold no pid) --
   * hard-killing the tree only as a fallback when we do know the pid. It then waits for health
   * to actually drop before respawning, so ensureRunning() cannot mistake the still-dying old
   * instance for a healthy one and skip the restart (which would keep the old code running).
   */
  async restart(): Promise<EnsureResult> {
    const stopped = await this.deps.shutdownFn()
    if (!stopped && this.pid !== null) {
      this.deps.killFn(this.pid)
    }
    this.pid = null
    const deadline = Date.now() + this.deps.timeoutMs
    while (Date.now() < deadline) {
      if (!(await this.deps.fetchHealthy())) {
        break
      }
      await new Promise((resolve) => setTimeout(resolve, this.deps.pollMs))
    }
    return this.ensureRunning()
  }
}
