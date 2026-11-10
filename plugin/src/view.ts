// The dashboard view: an Electron webview (iframe fallback) inside an ItemView.
import { ItemView, WorkspaceLeaf } from 'obsidian'
import { dashboardUrl } from './lifecycle'

export const VIEW_TYPE_SPYGLASS = 'spyglass-dashboard'

/** Hosts the dashboard web app; state lives server-side so reloads are safe. */
export class SpyglassView extends ItemView {
  private port: number
  private useIframe: boolean

  constructor(leaf: WorkspaceLeaf, port: number, useIframe: boolean) {
    super(leaf)
    this.port = port
    this.useIframe = useIframe
  }

  getViewType(): string {
    return VIEW_TYPE_SPYGLASS
  }

  getDisplayText(): string {
    return 'Spyglass'
  }

  getIcon(): string {
    return 'telescope'
  }

  async onOpen(): Promise<void> {
    const container = this.containerEl.children[1] as HTMLElement
    container.empty()
    container.addClass('spyglass-view')
    const url = dashboardUrl(this.port)
    if (this.useIframe) {
      const frame = container.createEl('iframe')
      frame.src = url
      frame.setAttribute('style', 'width:100%;height:100%;border:none;')
    } else {
      // Electron webview: out-of-process, ignores frame headers (research note).
      const webview = container.createEl('webview' as keyof HTMLElementTagNameMap)
      webview.setAttribute('src', url)
      webview.setAttribute('partition', 'persist:spyglass')
      webview.setAttribute('style', 'width:100%;height:100%;')
    }
  }
}
