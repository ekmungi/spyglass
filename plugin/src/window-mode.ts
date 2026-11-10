// Pure window-mode helpers: types and browser executable resolution for the dashboard opener.
import { existsSync } from 'fs'

/** Which Chromium browser to use for the standalone app-window mode. */
export type BrowserChoice = 'chrome' | 'edge' | 'vivaldi' | 'custom'

/**
 * Build the CLI args that open a URL as a chromeless app window.
 * All Chromium-based browsers support the --app flag for this purpose.
 * @param url - The URL to open in the app window.
 * @returns An argument array to pass to the browser executable.
 */
export function buildAppWindowArgs(url: string): string[] {
  return [`--app=${url}`]
}

/**
 * Known Windows install locations for each supported Chromium browser.
 * Ordered from most-common install to least-common so the first hit wins.
 * These cover system-wide installs; per-user installs are handled via LOCALAPPDATA.
 */
export const KNOWN_BROWSER_PATHS: Record<Exclude<BrowserChoice, 'custom'>, string[]> = {
  chrome: [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  ],
  edge: [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  ],
  vivaldi: ['C:/Program Files/Vivaldi/Application/vivaldi.exe'],
}

/**
 * Resolve the executable path for the chosen browser, or null if none is found.
 *
 * For 'custom': returns customPath when it is non-empty and exists, else null.
 * For named browsers: checks KNOWN_BROWSER_PATHS entries in order, then appends
 * per-user LOCALAPPDATA candidates for chrome and vivaldi when that env var is set.
 * All paths use forward slashes to be consistent with the static entries above.
 *
 * @param browser - The browser choice from plugin settings.
 * @param customPath - Used only when browser is 'custom'.
 * @param exists - File-existence predicate; injectable so tests avoid the real filesystem.
 * @returns Absolute path to the browser executable, or null.
 */
export function resolveBrowserPath(
  browser: BrowserChoice,
  customPath: string,
  exists: (p: string) => boolean = existsSync,
): string | null {
  if (browser === 'custom') {
    return customPath && exists(customPath) ? customPath : null
  }

  const known = KNOWN_BROWSER_PATHS[browser]

  // Normalize LOCALAPPDATA to forward slashes so paths match the static ones.
  const rawLocalAppData = process.env.LOCALAPPDATA
  const localAppData = rawLocalAppData ? rawLocalAppData.replace(/\\/g, '/') : null

  const extra: string[] = []
  if (localAppData) {
    if (browser === 'chrome') {
      extra.push(`${localAppData}/Google/Chrome/Application/chrome.exe`)
    } else if (browser === 'vivaldi') {
      extra.push(`${localAppData}/Vivaldi/Application/vivaldi.exe`)
    }
    // Edge has no common per-user install path, so it gets no LOCALAPPDATA entry.
  }

  const candidates = [...known, ...extra]
  return candidates.find((p) => exists(p)) ?? null
}
