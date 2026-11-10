// Pure lifecycle helpers: URLs and the spawn specification for the service.

export interface SpawnSettings {
  repoPath: string
  port: number
  // Passed to the service as env so the plugin controls where research is written;
  // env overrides any .env values. vaultPath comes from Obsidian automatically.
  vaultPath?: string
  researchFolder?: string
  // Absolute path for the service's data directory (DB + embedding model).
  // Blank means use the service default (~/.spyglass). Forwarded only when non-empty.
  dataDir?: string
}

export interface SpawnSpecification {
  command: string
  args: string[]
  options: {
    cwd: string
    windowsHide: boolean
    env: Record<string, string>
  }
}

/** Shown when the plugin should start the service but does not know where the repository is. */
export const REPO_PATH_NOTICE =
  'Spyglass: set "Service repository path" in Settings → Spyglass to the folder you cloned ' +
  'Spyglass into, or turn on "Connect only" if you start the service yourself.'

/** True when the plugin manages the service but no repository folder is set, so it cannot
 *  start one. Connect-only mode never starts the service, so it needs no folder. */
export function needsRepoPath(settings: { repoPath: string; connectOnly: boolean }): boolean {
  return !settings.connectOnly && settings.repoPath.trim() === ''
}

/** Health endpoint polled by the supervisor. */
export function healthUrl(port: number): string {
  return `http://127.0.0.1:${port}/api/health`
}

/** Root URL the WebView loads. */
export function dashboardUrl(port: number): string {
  return `http://127.0.0.1:${port}/`
}

/** How to start the service: the repo's own venv interpreter, hidden console.
 *  The deterministic .venv location is part of the project's cleanliness rules. */
export function spawnSpec(settings: SpawnSettings): SpawnSpecification {
  const env: Record<string, string> = { SPYGLASS_PORT: String(settings.port) }
  if (settings.vaultPath) {
    env.SPYGLASS_VAULT_PATH = settings.vaultPath
  }
  if (settings.researchFolder) {
    env.SPYGLASS_BRIEFING_SUBDIR = settings.researchFolder
  }
  if (settings.dataDir) {
    env.SPYGLASS_DATA_DIR = settings.dataDir
  }
  return {
    command: `${settings.repoPath}/.venv/Scripts/python.exe`,
    args: ['-m', 'spyglass_service'],
    options: { cwd: settings.repoPath, windowsHide: true, env },
  }
}
