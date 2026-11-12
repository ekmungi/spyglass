// background.js - the extension's service worker. It does all the sending, so a send is not
// cut short when the popup closes. Three things start a send, each only by the reader's own act:
// the popup's buttons, the right-click menu and the keyboard shortcut. Nothing runs on its own.

import { LIMITS, buildPayload, classifyPage, describeOutcome, sendToSpyglass } from './lib.js'
import { collectInPage } from './reader.js'
import { loadSettings } from './store.js'

const MENU_PAGE = 'send-page'
const MENU_SELECTION = 'send-selection'

/**
 * Read the page in a tab after the reader's click (allowed by the activeTab permission).
 * @param {number} tabId
 * @param {'page' | 'selection'} kind
 * @returns {Promise<object | null>} what the page returned, or null when it cannot be read
 */
async function readTab(tabId, kind) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: collectInPage,
      args: [kind, LIMITS.fallbackChars],
    })
    return (results && results[0] && results[0].result) || null
  } catch {
    // Browser pages, the web store and the built-in PDF viewer refuse scripts.
    return null
  }
}

/**
 * Send the page or the selection of a tab to Spyglass.
 * @param {number} tabId
 * @param {'page' | 'selection'} kind
 * @param {string} [note] the reader's note
 * @returns {Promise<{ok: boolean, message: string, hint?: string, itemId?: number, address?: string}>}
 */
export async function sendTab(tabId, kind, note = '') {
  const settings = await loadSettings()
  if (!settings.key) return describeOutcome({ kind: 'no-key' })
  const tab = await chrome.tabs.get(tabId).catch(() => null)
  const sort = classifyPage(tab && tab.url)
  if (!tab || sort === 'internal') return describeOutcome({ kind: 'unreadable' })
  if (sort === 'pdf') return describeOutcome({ kind: 'pdf' })
  const read = await readTab(tabId, kind)
  if (!read) return describeOutcome({ kind: 'unreadable' })
  const built = buildPayload(read, kind, note)
  if (!built.ok) return describeOutcome({ kind: built.reason })
  const outcome = await sendToSpyglass({ address: settings.address, key: settings.key, payload: built.payload })
  const result = describeOutcome(outcome)
  if (outcome.kind === 'ok' && outcome.data && Number.isInteger(outcome.data.item_id)) {
    return { ...result, itemId: outcome.data.item_id, address: settings.address }
  }
  return result
}

/**
 * Show a desktop notification with the result of a send started from the menu or the keyboard.
 * @param {{ok: boolean, message: string, hint?: string}} result
 */
function notify(result) {
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon-128.png',
    title: result.ok ? 'Send to Spyglass' : 'Send to Spyglass: not sent',
    message: result.hint ? `${result.message} ${result.hint}` : result.message,
  })
}

/** Make the two right-click entries (called again on every install or update). */
function createMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU_PAGE, title: 'Send this page to Spyglass', contexts: ['page', 'frame'] })
    chrome.contextMenus.create({ id: MENU_SELECTION, title: 'Send selected text to Spyglass', contexts: ['selection'] })
  })
}

chrome.runtime.onInstalled.addListener((details) => {
  createMenus()
  // The first time, open the settings so the reader can paste the key.
  if (details.reason === 'install') chrome.runtime.openOptionsPage()
})

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || tab.id === undefined) return
  const kind = info.menuItemId === MENU_SELECTION ? 'selection' : 'page'
  sendTab(tab.id, kind).then(notify)
})

chrome.commands.onCommand.addListener((command, tab) => {
  if (command !== 'send-page' || !tab || tab.id === undefined) return
  sendTab(tab.id, 'page').then(notify)
})

// The popup asks for a send and gets the result back. Only messages from this extension arrive.
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !message || message.type !== 'send') return false
  const kind = message.kind === 'selection' ? 'selection' : 'page'
  sendTab(Number(message.tabId), kind, String(message.note || '')).then(respond)
  return true
})
