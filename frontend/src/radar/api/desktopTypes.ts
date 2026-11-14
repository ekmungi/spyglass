// Shapes of the desktop app's routes (GET/PUT /desktop/autostart, /desktop/browsers, /desktop/extension).

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
