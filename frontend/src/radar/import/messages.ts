// What the import window accepts from the "Send to Spyglass" button, and how it describes where
// a page came from. Pure functions, so the rules are tested on their own.
import { PAGE_MESSAGE } from './bookmarklet'

/** The page as the button sends it. */
export interface PageMessage {
  url: string
  title: string
  html: string
  /** The button's secret, passed on to the service, which checks it. */
  key: string
}

// The same limits the service applies: an address of at most 2,048 characters and a page of at
// most 6 MB (counted here in characters; the service counts bytes and has the last word).
export const MAX_URL_CHARS = 2048
export const MAX_TITLE_CHARS = 2000
export const MAX_HTML_CHARS = 6 * 1024 * 1024
// An origin is at most a scheme, a host and a port.
const MAX_ORIGIN_CHARS = 300
const MAX_KEY_CHARS = 100

/** Read a postMessage payload as a page, or null when its shape or size is not exactly right. */
export function readPageMessage(data: unknown): PageMessage | null {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
  const value = data as Record<string, unknown>
  if (value.type !== PAGE_MESSAGE) return null
  const { url, html } = value
  const title = value.title ?? ''
  const key = value.key ?? ''
  if (typeof url !== 'string' || url.length === 0 || url.length > MAX_URL_CHARS) return null
  if (typeof title !== 'string' || title.length > MAX_TITLE_CHARS) return null
  if (typeof html !== 'string' || html.trim().length === 0 || html.length > MAX_HTML_CHARS) return null
  if (typeof key !== 'string' || key.length > MAX_KEY_CHARS) return null
  return { url, title, html, key }
}

/** Whether a message's origin is a real http(s) origin that can be answered (not "null"). */
export function isAnswerableOrigin(origin: string): boolean {
  if (origin.length > MAX_ORIGIN_CHARS) return false
  try {
    const parsed = new URL(origin)
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.origin === origin
  } catch {
    return false
  }
}

/**
 * The line the confirmation window shows when the site that really sent the page is not the site
 * the page says it is from (the service decides; `matches` is its answer). Null when they match.
 */
export function senderMismatchLine(sender: string | null, claimedHost: string, matches: boolean): string | null {
  if (matches) return null
  return `This page was sent by ${sender ?? 'an unknown site'}, but says it is from ${claimedHost}.`
}

/** Shown in place of the Add button when a page from another site would replace an existing item. */
export const REPLACE_REFUSED_MESSAGE = 'A page sent from another site cannot replace an article you already have.'

/** The plain sentence for an error code the service puts in the address after a form post. */
export function stageErrorMessage(code: string): string {
  switch (code) {
    case 'address':
      return 'Spyglass only accepts public web pages (http or https addresses). This page was not added.'
    case 'size':
      return 'This page is larger than 6 MB. Save it from your browser and use Add a file in Spyglass instead.'
    case 'empty':
      return 'The page arrived empty. Try the button again once the page has finished loading.'
    case 'key':
      return 'This Send to Spyglass button is out of date. Make a new button in Settings and replace the one in your bookmarks bar.'
    case 'origin':
      return 'Your browser did not say which site sent the page, so Spyglass did not take it. Send it from the window button on another page, or save the page and use Add a file.'
    default:
      return 'The page could not be read. Try the button again, or save the page and use Add a file.'
  }
}

/** The service's limit for one file, in megabytes; the one number every message below is built from. */
export const MAX_FILE_MB = 150
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
const FILE_ENDINGS = ['.pdf', '.html', '.htm', '.mhtml', '.mht']
/** The file picker's filter. */
export const FILE_ACCEPT = FILE_ENDINGS.join(',')

/** Why a chosen file cannot be sent, or null when it can. */
export function fileProblem(file: File | null): string | null {
  if (!file) return 'Choose a file to add.'
  const name = file.name.toLowerCase()
  if (!FILE_ENDINGS.some((ending) => name.endsWith(ending))) return 'Choose a .pdf, .html or .mhtml file saved from your browser.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_FILE_BYTES) return `The file is larger than ${MAX_FILE_MB} MB.`
  return null
}
