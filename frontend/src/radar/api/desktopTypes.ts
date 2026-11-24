// Shapes of the desktop app's routes (GET/PUT /desktop/autostart, /desktop/browsers, /desktop/extension,
// /desktop/capabilities, /desktop/first-start).

/** Whether the "Start with Windows" switch is offered (not in a developer run) and whether it is on. */
export interface Autostart {
  available: boolean
  enabled: boolean
}

/** One installed browser that has an extensions page Spyglass can open. */
export interface DesktopBrowser {
  id: string
  name: string
}

/** The folder holding this install's copy of the browser extension; it may not exist yet. */
export interface ExtensionFolder {
  folder: string
}

/** One optional part setup left out: what it changes, and how to add it. */
export interface MissingPart {
  id: string
  name: string
  effect: string
  how_to_add: string
}

/** Which optional parts this install has (GET /desktop/capabilities). */
export interface Capabilities {
  pdf_reading: 'full' | 'basic'
  local_ai: boolean
  missing: MissingPart[]
}

/** What the first-start page needs (GET /desktop/first-start). */
export interface FirstStart {
  /** True only on the first start of a fresh install, when the data folder is still to be confirmed. */
  needed: boolean
  /** The data folder in use now, which the page offers as the suggestion. */
  data_dir: string
  /** The Obsidian vault already chosen, or null. */
  vault_path: string | null
  /** The browsers setup asked a "Load unpacked" guide for; empty when none. */
  browsers: DesktopBrowser[]
}

/** The answer to saving the first-start choices (POST /desktop/first-start). */
export interface FirstStartSaved {
  /** True when the data folder changed: Spyglass stops and starts again on the new folder. */
  restart: boolean
  data_dir: string
}

/** The body of POST /desktop/first-start; an empty vault is sent as null. */
export interface FirstStartChoice {
  data_dir: string
  vault_path: string | null
}
