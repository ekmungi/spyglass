// popup.js - the window behind the toolbar button. It shows the page's site and title, takes an
// optional note, and asks the background script to send the page or the selected text. All text
// from the page (the title, the site) is shown with textContent, never as HTML.

import { classifyPage, describeOutcome, itemUrl, siteOf } from './lib.js'
import { hasSelectionInPage } from './reader.js'
import { loadSettings } from './store.js'

const elements = {
  site: document.getElementById('site'),
  title: document.getElementById('title'),
  note: document.getElementById('note'),
  sendPage: document.getElementById('send-page'),
  sendSelection: document.getElementById('send-selection'),
  status: document.getElementById('status'),
  hint: document.getElementById('hint'),
  open: document.getElementById('open'),
  settings: document.getElementById('settings'),
}

/** The tab the reader clicked the button on. */
let activeTab = null

/**
 * Show a message under the buttons.
 * @param {{ok?: boolean, message: string, hint?: string} | null} result null clears the message
 */
function show(result) {
  elements.status.textContent = result ? result.message : ''
  elements.status.className = result ? (result.ok ? 'status ok' : 'status error') : 'status'
  elements.hint.textContent = result && result.hint ? result.hint : ''
}

/**
 * Turn the two send buttons on or off.
 * @param {boolean} page whether "Send this page" is available
 * @param {boolean} selection whether "Send selected text" is available
 */
function setButtons(page, selection) {
  elements.sendPage.disabled = !page
  elements.sendSelection.disabled = !selection
}

/**
 * Ask the background script to send, then show the result and, on success, "Open in Spyglass".
 * @param {'page' | 'selection'} kind
 */
async function send(kind) {
  setButtons(false, false)
  show({ message: 'Sending…' })
  elements.open.hidden = true
  let result = null
  try {
    result = await chrome.runtime.sendMessage({ type: 'send', tabId: activeTab.id, kind, note: elements.note.value })
  } catch {
    result = null
  }
  if (!result) {
    show({ ok: false, message: 'The extension did not answer. Close this window and try again.' })
    setButtons(true, kind === 'selection')
    return
  }
  show(result)
  if (result.ok && Number.isInteger(result.itemId)) {
    elements.open.hidden = false
    elements.open.onclick = () => {
      chrome.tabs.create({ url: itemUrl(result.address, result.itemId) })
      window.close()
    }
  } else {
    setButtons(true, kind === 'selection')
  }
}

/** Fill in the page's site and title, and switch on the buttons that can work on this page. */
async function start() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  activeTab = tab || null
  elements.site.textContent = siteOf(tab && tab.url)
  elements.title.textContent = (tab && tab.title) || ''
  elements.settings.onclick = () => {
    chrome.runtime.openOptionsPage()
    window.close()
  }
  elements.sendPage.onclick = () => send('page')
  elements.sendSelection.onclick = () => send('selection')
  const sort = classifyPage(tab && tab.url)
  if (!tab || sort !== 'ok') {
    show(describeOutcome({ kind: sort === 'pdf' ? 'pdf' : 'unreadable' }))
    return
  }
  const settings = await loadSettings()
  if (!settings.key) show(describeOutcome({ kind: 'no-key' }))
  let selected = false
  try {
    const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: hasSelectionInPage })
    selected = Boolean(results && results[0] && results[0].result)
  } catch {
    show(describeOutcome({ kind: 'unreadable' }))
    return
  }
  setButtons(true, selected)
}

start()
