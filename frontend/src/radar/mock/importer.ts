// Sample mode for bringing in a page: staged pages wait under a token, accepting one adds a
// from-you item, and pasted text or a file is added at once. Mirrors the service's replies.
import type { RadarItem, StagedImport } from '../api/types'
import { addCapturedItem, mockState } from './store'

const staged = new Map<string, StagedImport>()
const REPLACE_REFUSED = 'A page sent from another site cannot replace an article you already have.'
let buttonKey = newToken()
const GONE = 'This page is no longer waiting. Send it again from your browser.'

/** Forget every staged page (tests, and a fresh visit to sample mode). */
export function resetImportMock(): void {
  staged.clear()
  buttonKey = newToken()
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

/** 32 random hex characters, like the service's tokens. */
function newToken(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function hostOf(url: string): string | null {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.hostname : null
  } catch {
    return null
  }
}

/** A host without a leading "www.", for the sample mode's rough same-site comparison. */
function bareHost(host: string): string {
  return host.toLowerCase().replace(/^www\./, '')
}

/** Plain text of a page, read in an inert document (nothing in it runs). */
function textOf(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('script, style, nav, header, footer').forEach((node) => node.remove())
  return (doc.body?.textContent ?? '').replace(/\s+/g, ' ').trim()
}

/** Add the item the way the service does, with the channel and title of the import. */
function addItem(url: string, title: string, via: string): RadarItem {
  const item = addCapturedItem(url, undefined)
  const updated: RadarItem = {
    ...item,
    title: title || item.title,
    headline: title || item.headline,
    has_reader: true,
    state: { ...item.state, captured_via: via },
  }
  const current = mockState()
  current.items = current.items.map((entry) => (entry.id === item.id ? updated : entry))
  return updated
}

function stage(body: Record<string, unknown>): Response {
  const url = String(body.url ?? '')
  const host = hostOf(url)
  if (!host || host === 'localhost') return json({ detail: 'Links to this computer or a private network are not accepted.' }, 400)
  const html = String(body.html ?? '')
  const text = textOf(html)
  const token = newToken()
  if (body.key !== buttonKey) return json({ detail: 'This Send to Spyglass button is out of date. Make a new button in Settings.' }, 403)
  const sender = typeof body.sender === 'string' ? hostOf(body.sender) : null
  const existing = mockState().items.find((item) => item.url === url)?.id ?? null
  staged.set(token, {
    token,
    url,
    host,
    title: String(body.title ?? ''),
    site: host,
    word_count: text ? text.split(' ').length : 0,
    excerpt: text.slice(0, 600),
    sender,
    sender_matches: sender !== null && bareHost(sender) === bareHost(host),
    existing_item_id: existing,
    replaces_existing: existing !== null,
    replace_refused: existing !== null && !(sender !== null && bareHost(sender) === bareHost(host)),
  })
  return json({ token })
}

/** Route one sample import request; null when the path is not an import path. */
export function importRoute(method: string, parts: string[], body: Record<string, unknown>, form: FormData | null): Response | null {
  if (parts[0] !== 'import') return null
  if (method === 'GET' && parts[1] === 'button-key') return json({ key: buttonKey })
  if (method === 'POST' && parts[1] === 'button-key' && parts[2] === 'rotate') {
    buttonKey = newToken()
    return json({ key: buttonKey })
  }
  if (method === 'POST' && parts[1] === 'stage') return stage(body)
  if (parts[1] === 'staged' && parts[2]) {
    const page = staged.get(parts[2])
    if (!page) return json({ detail: GONE }, 404)
    if (method === 'GET' && parts.length === 3) return json(page)
    if (method === 'POST' && parts[3] === 'accept' && page.replace_refused) return json({ detail: REPLACE_REFUSED }, 409)
    staged.delete(parts[2])
    if (method === 'DELETE') return new Response(null, { status: 204 })
    if (method === 'POST' && parts[3] === 'accept') return json(addItem(page.url, page.title, 'browser'))
  }
  if (method === 'POST' && parts[1] === 'text') {
    const url = String(body.url ?? '')
    if (!hostOf(url)) return json({ detail: 'Only http and https links can be captured.' }, 400)
    if (!String(body.text ?? '').trim()) return json({ detail: 'Paste the text of the article first.' }, 400)
    const firstLine = String(body.text).trim().split('\n')[0].slice(0, 200)
    return json(addItem(url, String(body.title ?? '') || firstLine, 'paste'))
  }
  if (method === 'POST' && parts[1] === 'file') {
    const url = String(form?.get('url') ?? '')
    const file = form?.get('file')
    if (!hostOf(url)) return json({ detail: 'Only http and https links can be captured.' }, 400)
    if (!(file instanceof File)) return json({ detail: 'Choose a file to add.' }, 400)
    return json(addItem(url, file.name.replace(/\.[^.]+$/, ''), 'file'))
  }
  return null
}
