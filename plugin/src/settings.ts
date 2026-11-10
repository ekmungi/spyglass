// Plugin settings: where the service repo lives and how to reach the dashboard.
import { App, PluginSettingTab, Setting } from 'obsidian'
import type SpyglassPlugin from './main'
import { type BrowserChoice } from './window-mode'

export interface SpyglassSettings {
  repoPath: string
  port: number
  connectOnly: boolean
  useIframe: boolean
  // Vault-relative folder where briefings / literature notes are written.
  researchFolder: string
  // Which browser to use for the browser-app window mode.
  browser: BrowserChoice
  // Absolute path to a custom browser executable (used when browser is 'custom').
  browserPath: string
  // Absolute path for the service data directory (DB + embedding model).
  // Blank means use the service default (~/.spyglass). Keep OUT of a synced vault.
  dataDir: string
  // Whether the plugin should automatically refresh the collection on a timer.
  autoRefresh: boolean
  // How often (in minutes) the background refresh fires (minimum 1).
  refreshIntervalMinutes: number
  // Fire one collection refresh shortly after Obsidian starts.
  refreshOnStartup: boolean
}

export const DEFAULT_SETTINGS: SpyglassSettings = {
  // Blank until the user points it at their clone; the plugin shows a notice until then.
  repoPath: '',
  port: 7777,
  connectOnly: false,
  // Default to iframe: it is fully interactive for a localhost SPA in Obsidian.
  // The Electron <webview> swallows input events in some Obsidian builds.
  useIframe: true,
  researchFolder: '03 RESOURCES/Research/Spyglass',
  browser: 'chrome',
  browserPath: '',
  dataDir: '',
  autoRefresh: true,
  refreshIntervalMinutes: 60,
  refreshOnStartup: false,
}

/** Settings tab: repo path, port, connect-only mode, iframe fallback. */
export class SpyglassSettingTab extends PluginSettingTab {
  private plugin: SpyglassPlugin

  constructor(app: App, plugin: SpyglassPlugin) {
    super(app, plugin)
    this.plugin = plugin
  }

  display(): void {
    const { containerEl } = this
    containerEl.empty()

    new Setting(containerEl)
      .setName('Service repository path')
      .setDesc(
        'Folder containing the Spyglass repo (with its .venv). Required unless "Connect only" is on.',
      )
      .addText((text) =>
        text.setValue(this.plugin.settings.repoPath).onChange(async (value) => {
          this.plugin.settings.repoPath = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Port')
      .setDesc('Localhost port the service listens on.')
      .addText((text) =>
        text.setValue(String(this.plugin.settings.port)).onChange(async (value) => {
          const port = Number(value)
          if (Number.isInteger(port) && port > 0) {
            this.plugin.settings.port = port
            await this.plugin.saveSettings()
          }
        }),
      )

    new Setting(containerEl)
      .setName('Restart service')
      .setDesc('Stop and restart the Spyglass service to load new code (e.g. after updating the repo).')
      .addButton((btn) =>
        btn
          .setButtonText('Restart')
          .setCta()
          .onClick(async () => {
            btn.setButtonText('Restarting…').setDisabled(true)
            await this.plugin.restartService()
            btn.setButtonText('Restart').setDisabled(false)
          }),
      )

    new Setting(containerEl)
      .setName('Research folder')
      .setDesc('Vault-relative folder where briefings and literature notes are saved.')
      .addText((text) =>
        text.setValue(this.plugin.settings.researchFolder).onChange(async (value) => {
          this.plugin.settings.researchFolder = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Connect only')
      .setDesc('Never start the service; only connect to an already-running one.')
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.connectOnly).onChange(async (value) => {
          this.plugin.settings.connectOnly = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Use iframe instead of webview')
      .setDesc('Default and recommended. Turn off to use the Electron webview instead.')
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.useIframe).onChange(async (value) => {
          this.plugin.settings.useIframe = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Browser (for standalone browser window)')
      .setDesc('Which Chromium browser to use for the dashboard app window. Falls back to an Obsidian popout when not found.')
      .addDropdown((d) =>
        d
          .addOption('chrome', 'Google Chrome')
          .addOption('edge', 'Microsoft Edge')
          .addOption('vivaldi', 'Vivaldi')
          .addOption('custom', 'Custom (specify path below)')
          .setValue(this.plugin.settings.browser)
          .onChange(async (value) => {
            this.plugin.settings.browser = value as BrowserChoice
            await this.plugin.saveSettings()
          }),
      )

    new Setting(containerEl)
      .setName('Custom browser path')
      .setDesc('Absolute path to the browser executable. Used when Browser is set to "Custom".')
      .addText((text) =>
        text.setValue(this.plugin.settings.browserPath).onChange(async (value) => {
          this.plugin.settings.browserPath = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Data directory')
      .setDesc(
        'Local folder for the DB and embedding model. Blank = ~/.spyglass. Keep it OUT of a synced vault.',
      )
      .addText((text) =>
        text.setValue(this.plugin.settings.dataDir).onChange(async (value) => {
          this.plugin.settings.dataDir = value
          await this.plugin.saveSettings()
        }),
      )

    new Setting(containerEl)
      .setName('Auto-refresh')
      .setDesc('Automatically refresh the collection on a timer in the background.')
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.autoRefresh).onChange(async (value) => {
          this.plugin.settings.autoRefresh = value
          await this.plugin.saveSettings()
          this.plugin.rescheduleAutoRefresh()
        }),
      )

    new Setting(containerEl)
      .setName('Refresh interval (minutes)')
      .setDesc('How often the background refresh fires. Minimum 1.')
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.refreshIntervalMinutes))
          .onChange(async (value) => {
            const minutes = Math.max(1, parseInt(value, 10) || 60)
            this.plugin.settings.refreshIntervalMinutes = minutes
            await this.plugin.saveSettings()
            this.plugin.rescheduleAutoRefresh()
          }),
      )

    new Setting(containerEl)
      .setName('Refresh on startup')
      .setDesc('Fire one collection refresh shortly after Obsidian starts.')
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.refreshOnStartup).onChange(async (value) => {
          this.plugin.settings.refreshOnStartup = value
          await this.plugin.saveSettings()
        }),
      )
  }
}
