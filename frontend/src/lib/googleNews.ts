// Helpers for building Google News RSS search URLs.
// Used by DiscoverPanel to offer a fallback feed for bot-blocked sites.

/**
 * Build a Google News RSS search URL for a given topic and/or site.
 * At least one of topic or site should be non-empty for a useful URL.
 * Both empty is valid at the function level; the caller should disable
 * the submit button in that case.
 *
 * @param topic - Optional free-text topic to search for.
 * @param site  - Optional site hostname to scope the search (e.g. "example.com").
 * @returns A fully-formed Google News RSS URL with encoded query params.
 */
export function googleNewsUrl(topic?: string, site?: string): string {
  const parts: string[] = []
  const trimmedTopic = topic?.trim() ?? ''
  if (trimmedTopic) parts.push(trimmedTopic)
  if (site) parts.push(`site:${site}`)
  const q = parts.join(' ')
  const params = new URLSearchParams({ q, hl: 'en-US', gl: 'US', ceid: 'US:en' })
  return `https://news.google.com/rss/search?${params.toString()}`
}

/**
 * Extract the hostname from a URL, stripping a leading "www." prefix.
 * Returns an empty string if the URL cannot be parsed.
 *
 * @param url - A full URL string (e.g. "https://www.example.com/page").
 * @returns The hostname without "www." (e.g. "example.com"), or "".
 */
export function siteFromUrl(url: string): string {
  try {
    const { hostname } = new URL(url)
    return hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}
