// safeUrl: the one place an address coming from data (an item, a source, a paper) is vetted
// before it becomes a link or is opened. Only plain web addresses pass.

/**
 * Return the normalised address when `url` is an absolute http: or https: address, otherwise null.
 * Rejects javascript:, data:, file:, relative paths, empty and non-string values.
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null
  const trimmed = url.trim()
  if (!trimmed) return null
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return null
  }
  return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
}

/**
 * Open a vetted address in a new tab without giving the page access to this window.
 * Returns false (and opens nothing) when the address is not a plain web address.
 */
export function openExternal(url: string | null | undefined): boolean {
  const safe = safeHttpUrl(url)
  if (!safe) return false
  window.open(safe, '_blank', 'noopener,noreferrer')
  return true
}
