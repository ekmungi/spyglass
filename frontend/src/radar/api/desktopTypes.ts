// Shapes of the desktop app's routes (GET/PUT /desktop/autostart, /desktop/browsers, /desktop/extension,
// /desktop/capabilities).

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
