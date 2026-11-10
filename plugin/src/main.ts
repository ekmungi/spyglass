// Spyglass plugin entry: thin shell that supervises the service and opens the
// dashboard WebView. All business logic lives in the Python service.
import { spawn } from 'child_process'
import { FileSystemAdapter, Notice, Plugin, requestUrl, WorkspaceLeaf } from 'obsidian'
import { AutoRefresher, formatLastRefreshed, healthyForRefresh } from './autorefresh'
import { dashboardUrl, healthUrl, needsRepoPath, REPO_PATH_NOTICE, spawnSpec } from './lifecycle'
import { ServiceManager } from './service'
import { DEFAULT_SETTINGS, SpyglassSettingTab, type SpyglassSettings } from './settings'
import { SpyglassView, VIEW_TYPE_SPYGLASS } from './view'
import { buildAppWindowArgs, resolveBrowserPath } from './window-mode'

export default class SpyglassPlugin extends Plugin {
  settings: SpyglassSettings = DEFAULT_SETTINGS
  private manager: ServiceManager | null = null
  private autoRefresher: AutoRefresher | null = null
  // Interval handle owned by this plugin (tracked for rescheduling).
  // Registered via registerInterval so Obsidian also auto-clears on unload.
  private refreshIntervalId: number | null = null
  // Timestamp (ms) of the last successful collection refresh.
  private lastRefreshedAt: number | null = null
  // Status-bar element showing last-refreshed time.
  private statusBarEl: HTMLElement | null = null

  async onload(): Promise<void> {
    await this.loadSettings()
    this.addSettingTab(new SpyglassSettingTab(this.app, this))
    if (needsRepoPath(this.settings)) {
      new Notice(REPO_PATH_NOTICE, 10000)
    }
    this.registerView(
      VIEW_TYPE_SPYGLASS,
      (leaf) => new SpyglassView(leaf, this.settings.port, this.settings.useIframe),
    )
    this.addRibbonIcon('telescope', 'Open Spyglass', () => this.openDashboard())
    this.addCommand({
      id: 'open-dashboard',
      name: 'Open dashboard',
      callback: () => this.openDashboard(),
    })

    // Status bar: shows last-refreshed time.
    this.statusBarEl = this.addStatusBarItem()
    this.updateStatusBar()

    // "Refresh now" command: bypasses backoff, runs a forced collection refresh.
    this.addCommand({
      id: 'spyglass-refresh-now',
      name: 'Refresh Spyglass now',
      callback: async () => {
        await this.autoRefresher?.forceTick()
        this.updateStatusBar()
      },
    })

    // "Restart service" command: stop the running service and start a fresh one, which loads
    // new backend code from the repo -- the way to pick up an update without hunting for the port.
    this.addCommand({
      id: 'spyglass-restart-service',
      name: 'Restart service',
      callback: () => this.restartService(),
    })

    // Keep the status bar relative time current (refresh every 60 s).
    this.registerInterval(
      window.setInterval(() => this.updateStatusBar(), 60_000),
    )

    // Wire up the auto-refresher after settings are loaded.
    this.buildAutoRefresher()
    this.scheduleAutoRefresh()

    // Optional: fire one refresh shortly after load (after service is likely healthy).
    if (this.settings.refreshOnStartup) {
      window.setTimeout(() => void this.autoRefresher?.tick(), 5_000)
    }
  }

  async onunload(): Promise<void> {
    if (!this.settings.connectOnly) {
      await this.manager?.stop()
    }
  }

  /** Rebuild the AutoRefresher instance (called when port or settings change). */
  private buildAutoRefresher(): void {
    const port = this.settings.port
    const isHealthy = async () => {
      try {
        const response = await requestUrl({ url: healthUrl(port), throw: false })
        return healthyForRefresh(response.status, response.json)
      } catch {
        return false
      }
    }
    const refresh = async () => {
      try {
        const response = await requestUrl({
          url: `http://127.0.0.1:${port}/api/refresh`,
          method: 'POST',
          throw: false,
        })
        return response.status === 200
      } catch {
        return false
      }
    }
    const onRefreshed = (atMs: number) => {
      this.lastRefreshedAt = atMs
      this.updateStatusBar()
    }
    const intervalMs = Math.max(1, this.settings.refreshIntervalMinutes) * 60_000
    this.autoRefresher = new AutoRefresher(
      { isHealthy, refresh, onRefreshed, now: () => Date.now() },
      intervalMs,
    )
  }

  /** Clear the existing refresh interval and create a new one from current settings.
   *  Call after toggling autoRefresh or changing refreshIntervalMinutes in the settings tab. */
  rescheduleAutoRefresh(): void {
    if (this.refreshIntervalId !== null) {
      window.clearInterval(this.refreshIntervalId)
      this.refreshIntervalId = null
    }
    this.buildAutoRefresher()
    this.scheduleAutoRefresh()
  }

  /** Register the repeating interval (only when autoRefresh is enabled). */
  private scheduleAutoRefresh(): void {
    if (!this.settings.autoRefresh) {
      return
    }
    const intervalMs = Math.max(1, this.settings.refreshIntervalMinutes) * 60_000
    this.refreshIntervalId = this.registerInterval(
      window.setInterval(() => void this.autoRefresher?.tick(), intervalMs),
    )
  }

  /** Update the status bar text from the current lastRefreshedAt value. */
  private updateStatusBar(): void {
    if (this.statusBarEl === null) {
      return
    }
    this.statusBarEl.setText(formatLastRefreshed(this.lastRefreshedAt, Date.now()))
  }

  /** Ensure the service runs, then open the dashboard per the configured window mode. */
  private async openDashboard(): Promise<void> {
    // Without a repository folder the plugin cannot start the service; a service the user
    // started by hand still works, so only stop here when nothing answers.
    if (needsRepoPath(this.settings) && !(await this.serviceHealthy())) {
      new Notice(REPO_PATH_NOTICE, 10000)
      return
    }
    const result = await this.buildManager().ensureRunning()
    if (result === 'failed') {
      new Notice(
        'Spyglass: the service did not start. Check the repository path in settings, ' +
          'or start it manually with "uv run python -m spyglass_service".',
        10000,
      )
      return
    }

    const { browser, browserPath, port } = this.settings
    const exe = resolveBrowserPath(browser, browserPath)
    if (exe) {
      spawn(exe, buildAppWindowArgs(dashboardUrl(port)), { windowsHide: false, detached: true })
      return
    }

    // Fallback when no Chromium-class browser is found: open inside Obsidian.
    new Notice('No Chromium browser found; opening the dashboard inside Obsidian.')
    const leaf: WorkspaceLeaf = this.app.workspace.openPopoutLeaf()
    await leaf.setViewState({ type: VIEW_TYPE_SPYGLASS, active: true })
  }

  /** Stop the service and start a fresh one so new backend code is loaded (e.g. after an
   *  update). No-op in connect-only mode, where the plugin does not manage the service. */
  async restartService(): Promise<void> {
    if (this.settings.connectOnly) {
      new Notice('Spyglass: connect-only mode is on; the plugin does not manage the service.')
      return
    }
    if (needsRepoPath(this.settings)) {
      new Notice(REPO_PATH_NOTICE, 10000)
      return
    }
    new Notice('Spyglass: restarting the service…')
    const result = await this.buildManager().restart()
    new Notice(
      result === 'failed'
        ? 'Spyglass: the service did not come back — check the repository path in settings.'
        : 'Spyglass: service restarted.',
    )
  }

  /** Build (or reuse) the supervisor with real spawn/fetch/kill implementations. */
  private buildManager(): ServiceManager {
    if (this.manager !== null) {
      return this.manager
    }
    const { repoPath, port, connectOnly, researchFolder, dataDir } = this.settings
    // The plugin knows the vault path from Obsidian and passes it to the service,
    // so the user does not have to configure it in .env.
    const adapter = this.app.vault.adapter
    const vaultPath = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : undefined
    const spec = spawnSpec({ repoPath, port, vaultPath, researchFolder, dataDir })
    this.manager = new ServiceManager({
      repoPath,
      port,
      fetchHealthy: () => this.serviceHealthy(port),
      spawnFn: () => {
        if (connectOnly) {
          throw new Error('connect-only mode: refusing to start the service')
        }
        const child = spawn(spec.command, spec.args, {
          cwd: spec.options.cwd,
          windowsHide: spec.options.windowsHide,
          env: { ...process.env, ...spec.options.env },
        })
        return { pid: child.pid ?? -1 }
      },
      shutdownFn: async () => {
        try {
          await requestUrl({
            url: `http://127.0.0.1:${port}/api/shutdown`,
            method: 'POST',
            throw: false,
          })
          return true
        } catch {
          return false
        }
      },
      killFn: (pid) => {
        // Windows: kill() only signals the direct pid; take down the tree.
        spawn('taskkill', ['/T', '/F', '/PID', String(pid)], { windowsHide: true })
      },
      pollMs: 500,
      timeoutMs: 15000,
    })
    return this.manager
  }

  /** True when a Spyglass service answers its health check on the port (default: the
   *  configured one). */
  private async serviceHealthy(port: number = this.settings.port): Promise<boolean> {
    try {
      // requestUrl is an Electron-level request: it bypasses the browser
      // CORS check that blocks fetch() from the app://obsidian.md origin.
      const response = await requestUrl({ url: healthUrl(port), throw: false })
      return response.status === 200
    } catch {
      return false
    }
  }

  async loadSettings(): Promise<void> {
    this.settings = { ...DEFAULT_SETTINGS, ...((await this.loadData()) ?? {}) }
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings)
  }
}
