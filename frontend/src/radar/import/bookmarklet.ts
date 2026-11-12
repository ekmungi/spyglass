// Builds the "Send to Spyglass" bookmark button: the readable source in bookmarklet.src.js,
// minified, pointed at the running Spyglass, and written as a javascript: link that survives
// being dragged to the bookmarks bar.
import source from './bookmarklet.src.js?raw'

/** The message the button sends with the page, and the answer the import window gives. */
export const PAGE_MESSAGE = 'spyglass:page'
export const ACK_MESSAGE = 'spyglass:ack'
/** Browsers keep bookmarks of up to about 2,000 characters reliably across platforms. */
export const MAX_BOOKMARKLET_LENGTH = 2000

const PLACEHOLDER = 'SPYGLASS_ORIGIN'
const KEY_PLACEHOLDER = 'SPYGLASS_KEY'
// This copy's secret: 128 random bits as 32 lower-case hex characters (see the service's import_key).
const KEY_PATTERN = /^[0-9a-f]{32}$/
// The Spyglass address the button posts to: http(s), a host name or address, an optional port.
const ORIGIN_PATTERN = /^https?:\/\/(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::\d{1,5})?$/
// Characters a javascript: link keeps as they are; every other character is percent-encoded so a
// bookmark cannot be cut short (#, space), mis-decoded (%) or rejected (quotes, braces, < >).
const KEEP = /[A-Za-z0-9\-_.~!$&'()*+,;=:@/?[\]]/
const WORD = /[A-Za-z0-9_$]/

/**
 * Remove comments and every space the code does not need. Strings are copied untouched. The source
 * must not contain regular expressions (a slash would be read as the start of a comment).
 */
export function minify(code: string): string {
  let out = ''
  let i = 0
  let pendingSpace = false
  while (i < code.length) {
    const char = code[i]
    const next = code[i + 1]
    if (char === "'" || char === '"') {
      const end = code.indexOf(char, i + 1)
      if (end < 0) throw new Error('unterminated string in the bookmark button source')
      if (pendingSpace && WORD.test(out.at(-1) ?? '')) out += ' '
      out += code.slice(i, end + 1)
      i = end + 1
      pendingSpace = false
    } else if (char === '/' && next === '*') {
      i = code.indexOf('*/', i + 2) + 2
      pendingSpace = true
    } else if (char === '/' && next === '/') {
      const end = code.indexOf('\n', i)
      i = end < 0 ? code.length : end
      pendingSpace = true
    } else if (/\s/.test(char)) {
      pendingSpace = true
      i += 1
    } else {
      // A space survives only between two characters that would otherwise merge into one word.
      if (pendingSpace && WORD.test(out.at(-1) ?? '') && WORD.test(char)) out += ' '
      out += char
      pendingSpace = false
      i += 1
    }
  }
  return out
}

/** Percent-encode every character a bookmark could mangle. */
export function encodeForBookmark(code: string): string {
  return Array.from(code, (char) => (KEEP.test(char) ? char : encodeURIComponent(char))).join('')
}

/** Whether `origin` is a plain http(s) origin the button may point at. */
export function isUsableOrigin(origin: string): boolean {
  return ORIGIN_PATTERN.test(origin)
}

/** Whether `key` has the shape of the service's button secret. */
export function isUsableKey(key: string): boolean {
  return KEY_PATTERN.test(key)
}

/**
 * The javascript: link of the bookmark button for the Spyglass at `origin` (normally
 * window.location.origin of the Settings page), carrying the secret `key`. Throws for an origin
 * that is not plain http(s) or a key that is not 32 hex characters.
 */
export function buildBookmarklet(origin: string, key: string): string {
  if (!isUsableOrigin(origin)) throw new Error(`cannot build the bookmark button for ${origin}`)
  if (!isUsableKey(key)) throw new Error('cannot build the bookmark button without its key')
  const code = minify(source).replace(PLACEHOLDER, `'${origin}'`).replace(KEY_PLACEHOLDER, `'${key}'`)
  return `javascript:${encodeForBookmark(code)}`
}
