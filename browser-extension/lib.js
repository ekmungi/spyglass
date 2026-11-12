// lib.js - the pure logic of the "Send to Spyglass" extension: address and key checks, the size
// rules for what is sent, the request to Spyglass and the plain sentences shown for each result.
// It uses no browser extension APIs, so the background script, the popup and the settings page
// import it, and so do the tests. It never logs, and it never keeps the key anywhere.

/** The address Spyglass listens on by default. */
export const DEFAULT_ADDRESS = 'http://localhost:7777'

/** Size rules. They mirror what the Spyglass service accepts (6 MB of page, 2 MB of text). */
export const LIMITS = {
  htmlBytes: 6 * 1024 * 1024,
  textBytes: 2 * 1024 * 1024,
  // The page is cut to this many characters when it is too big and has no article or main part.
  fallbackChars: 2000000,
  titleChars: 300,
  noteChars: 500,
}

/** How long to wait for Spyglass before giving up. A page is never sent a second time on its own. */
export const TIMEOUT_MS = 30000

const KEY_SHAPE = /^[0-9a-f]{32}$/
const ADDRESS_SHAPE = /^http:\/\/(localhost|127\.0\.0\.1):(\d{1,5})\/?$/i

/**
 * Check the address of Spyglass. Only http://localhost:<port> and http://127.0.0.1:<port> are
 * accepted, so the page can never be sent to another computer.
 * @param {unknown} input what the reader typed
 * @returns {{ok: true, address: string} | {ok: false, message: string}}
 */
export function normalizeAddress(input) {
  const match = ADDRESS_SHAPE.exec(String(input ?? '').trim())
  const port = match ? Number(match[2]) : 0
  if (!match || port < 1 || port > 65535) {
    return { ok: false, message: 'Use an address like http://localhost:7777 (this computer only, with the port).' }
  }
  return { ok: true, address: `http://${match[1].toLowerCase()}:${port}` }
}

/**
 * Clean up a pasted key and check its shape (the 32 letters and digits shown in Spyglass settings).
 * @param {unknown} input what was pasted
 * @returns {{ok: true, key: string} | {ok: false, message: string}}
 */
export function normalizeKey(input) {
  const key = String(input ?? '').trim().toLowerCase()
  if (!KEY_SHAPE.test(key)) {
    return { ok: false, message: 'That does not look like the key from Spyglass. Copy it again from Settings.' }
  }
  return { ok: true, key }
}

/**
 * Whether the extension can read a page, judged by its address alone.
 * @param {string | undefined} url the tab's address
 * @returns {'ok' | 'internal' | 'pdf'} 'internal' for browser pages and other non-web addresses;
 *   'pdf' for the browser's built-in PDF viewer, which cannot be read from here
 */
export function classifyPage(url) {
  let parsed
  try {
    parsed = new URL(String(url))
  } catch {
    return 'internal'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return 'internal'
  if (parsed.pathname.toLowerCase().endsWith('.pdf')) return 'pdf'
  return 'ok'
}

/**
 * The site of an address, without a leading "www.".
 * @param {string | undefined} url
 * @returns {string} the host, or an empty string when the address is not a web address
 */
export function siteOf(url) {
  try {
    return new URL(String(url)).hostname.replace(/^www\./i, '')
  } catch {
    return ''
  }
}

/**
 * The number of bytes a string takes when sent as UTF-8.
 * @param {string} text
 * @returns {number}
 */
export function byteLength(text) {
  return new TextEncoder().encode(text).length
}

/**
 * Cut a string so it fits in `maxBytes` bytes of UTF-8 (never in the middle of a character).
 * @param {string} text
 * @param {number} maxBytes
 * @returns {string}
 */
export function clipToBytes(text, maxBytes) {
  if (byteLength(text) <= maxBytes) return text
  let low = 0
  let high = text.length
  while (low < high) {
    const middle = Math.ceil((low + high) / 2)
    if (byteLength(text.slice(0, middle)) <= maxBytes) low = middle
    else high = middle - 1
  }
  // Do not end on half of a surrogate pair.
  const code = text.charCodeAt(low - 1)
  return text.slice(0, code >= 0xd800 && code <= 0xdbff ? low - 1 : low)
}

/**
 * Pick what to send of a page: all of it when it is at most 6 MB; otherwise its <article> or
 * <main> part when that fits; otherwise the first 2,000,000 characters.
 * @param {{full: string, article?: string | null, main?: string | null}} parts the page's HTML, and
 *   the HTML of its <article> and <main> elements (only needed when the page is large)
 * @returns {string}
 */
export function chooseHtml(parts) {
  const { full, article, main } = parts
  if (byteLength(full) <= LIMITS.htmlBytes) return full
  for (const part of [article, main]) {
    if (part && byteLength(part) <= LIMITS.htmlBytes) return part
  }
  return (article || main || full).slice(0, LIMITS.fallbackChars)
}

/**
 * Build the JSON body for Spyglass from what was read in the page. Only the address, title,
 * the page or selection and the note are sent; nothing else about the reader or the browser.
 * @param {{href: string, title?: string, contentType?: string, full?: string, article?: string | null,
 *   main?: string | null, selectionText?: string, selectionHtml?: string}} read what the page returned
 * @param {'page' | 'selection'} kind
 * @param {string} [note] the reader's optional note
 * @returns {{ok: true, payload: object} | {ok: false, reason: 'no-selection' | 'empty' | 'pdf'}}
 */
export function buildPayload(read, kind, note = '') {
  // The built-in PDF viewer can be reached by a script when the address does not end in ".pdf"
  // (for example arxiv.org/pdf/2005.14165). Its page holds no text, so say so instead of sending it.
  if (/^application\/pdf(;|$)/i.test(String(read.contentType ?? ''))) return { ok: false, reason: 'pdf' }
  const common = {
    url: read.href,
    title: String(read.title ?? '').trim().slice(0, LIMITS.titleChars),
    kind,
  }
  const trimmedNote = String(note ?? '').trim().slice(0, LIMITS.noteChars)
  const withNote = trimmedNote ? { note: trimmedNote } : {}
  if (kind === 'selection') {
    const text = clipToBytes(String(read.selectionText ?? ''), LIMITS.textBytes)
    if (!text.trim()) return { ok: false, reason: 'no-selection' }
    const html = String(read.selectionHtml ?? '')
    const body = html.trim() && byteLength(html) <= LIMITS.htmlBytes ? { html } : { text }
    return { ok: true, payload: { ...common, ...body, ...withNote } }
  }
  const html = chooseHtml({ full: String(read.full ?? ''), article: read.article, main: read.main })
  if (!html.trim()) return { ok: false, reason: 'empty' }
  return { ok: true, payload: { ...common, html, ...withNote } }
}

/**
 * Ask Spyglass something and report what happened as a plain object (never throws).
 * @param {{address: string, key: string, path: string, method: 'GET' | 'POST', payload?: object,
 *   fetchImpl?: typeof fetch, timeoutMs?: number}} request
 * @returns {Promise<{kind: 'ok', data: any} | {kind: 'no-key'} | {kind: 'http', status: number, detail: string}
 *   | {kind: 'network'} | {kind: 'timeout'}>}
 */
export async function callSpyglass(request) {
  const { address, key, path, method, payload, fetchImpl = globalThis.fetch, timeoutMs = TIMEOUT_MS } = request
  if (!key) return { kind: 'no-key' }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(`${address}${path}`, {
      method,
      headers: { 'X-Spyglass-Key': key, ...(payload ? { 'Content-Type': 'application/json' } : {}) },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
    })
    let body = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    if (response.ok) return { kind: 'ok', data: body ?? {} }
    const detail = body && typeof body.detail === 'string' ? body.detail.slice(0, 300) : ''
    return { kind: 'http', status: response.status, detail }
  } catch (error) {
    return error && error.name === 'AbortError' ? { kind: 'timeout' } : { kind: 'network' }
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Send a page or selection to Spyglass (one attempt; a POST is never repeated automatically).
 * @param {{address: string, key: string, payload: object, fetchImpl?: typeof fetch, timeoutMs?: number}} request
 */
export function sendToSpyglass(request) {
  return callSpyglass({ ...request, path: '/api/radar/import/direct', method: 'POST' })
}

/**
 * Ask Spyglass whether the address and the key are right.
 * @param {{address: string, key: string, fetchImpl?: typeof fetch, timeoutMs?: number}} request
 */
export function checkSpyglass(request) {
  return callSpyglass({ ...request, path: '/api/radar/import/direct/check', method: 'GET' })
}

const PDF_HINT = 'Download the file and add it in Spyglass.'

/**
 * The plain sentences for a result, for the popup, the notification and the settings page.
 * @param {{kind: string, status?: number, detail?: string, data?: any}} outcome from callSpyglass, or
 *   {kind: 'unreadable' | 'pdf' | 'no-selection' | 'empty'} from reading the page
 * @param {'send' | 'check'} [purpose]
 * @returns {{ok: boolean, message: string, hint?: string}}
 */
export function describeOutcome(outcome, purpose = 'send') {
  switch (outcome.kind) {
    case 'ok':
      if (purpose === 'check') return { ok: true, message: 'Connected to Spyglass' }
      return { ok: true, message: outcome.data && outcome.data.replaced ? 'Updated in Spyglass' : 'Added to Spyglass' }
    case 'no-key':
      return { ok: false, message: "The key is missing or wrong. Open the extension's settings." }
    case 'network':
      return { ok: false, message: 'Spyglass is not running on this computer.' }
    case 'timeout':
      return { ok: false, message: 'Spyglass did not answer within 30 seconds. The page may not have been added.' }
    case 'pdf':
      return { ok: false, message: 'This page cannot be read here.', hint: PDF_HINT }
    case 'unreadable':
      return { ok: false, message: 'This page cannot be read here.' }
    case 'no-selection':
      return { ok: false, message: 'Select some text on the page first.' }
    case 'empty':
      return { ok: false, message: 'This page has nothing to send.' }
    case 'http':
      return describeHttp(outcome)
    default:
      return { ok: false, message: 'Something went wrong. Try again.' }
  }
}

/**
 * The sentence for an answer from Spyglass that was not a success.
 * @param {{status?: number, detail?: string}} outcome
 * @returns {{ok: false, message: string}}
 */
function describeHttp(outcome) {
  const status = outcome.status ?? 0
  if (status === 403) return { ok: false, message: "The key is missing or wrong. Open the extension's settings." }
  if (status === 404) return { ok: false, message: 'This copy of Spyglass is too old for the extension. Update Spyglass.' }
  if (status === 413) return { ok: false, message: 'This page is too large to send.' }
  if (status === 429) {
    return { ok: false, message: outcome.detail || 'Too many pages were sent in a short time. Wait a few minutes.' }
  }
  if (status >= 500) return { ok: false, message: 'Spyglass had a problem adding this page.' }
  return { ok: false, message: outcome.detail || 'Spyglass could not add this page.' }
}

/**
 * The address that opens an item in the Spyglass interface.
 * @param {string} address Spyglass's address
 * @param {number} itemId
 * @returns {string}
 */
export function itemUrl(address, itemId) {
  return `${address}/#/item/${encodeURIComponent(String(itemId))}`
}
