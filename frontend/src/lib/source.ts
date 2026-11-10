// Origin labelling: show WHERE an item came from as a clean brand-ish name
// ("Forbes", "NVIDIA"), not a raw hostname or the collector that fetched it.

// Brands whose casing a naive capitalize would get wrong.
const KNOWN_CASING: Record<string, string> = {
  youtube: 'YouTube',
  github: 'GitHub',
  nvidia: 'NVIDIA',
  arxiv: 'arXiv',
  openai: 'OpenAI',
  deepmind: 'DeepMind',
  bbc: 'BBC',
  ieee: 'IEEE',
  mit: 'MIT',
  techcrunch: 'TechCrunch',
}

// Second-level labels that are really part of the TLD (bbc.co.uk, ox.ac.uk).
const MULTI_TLD = new Set(['co', 'com', 'org', 'net', 'ac', 'gov', 'edu'])

/** Capitalize a bare domain label unless its brand casing is known. */
function brandFromHost(host: string): string {
  const parts = host.replace(/^www\./, '').split('.')
  let label = parts.length >= 2 ? parts[parts.length - 2] : parts[0]
  if (parts.length >= 3 && MULTI_TLD.has(label)) {
    label = parts[parts.length - 3]
  }
  return KNOWN_CASING[label] ?? label.charAt(0).toUpperCase() + label.slice(1)
}

/** True when a stored origin is a hostname rather than a human feed title. */
function looksLikeHost(origin: string): boolean {
  return !origin.includes(' ') && origin.includes('.')
}

// Hosting platforms worth showing alongside the publication ("X · YouTube").
const PLATFORMS: [string, string][] = [
  ['youtube.com', 'YouTube'],
  ['youtu.be', 'YouTube'],
  ['medium.com', 'Medium'],
  ['substack.com', 'Substack'],
  ['github.com', 'GitHub'],
]

type SourceCard = { origin: string | null; url: string; source: string }

/** Display label combining publication and platform: "Stanford Medicine · YouTube".
 * The platform is appended only when it adds information (not already implied). */
export function sourceLabel(card: SourceCard): string {
  const label = originLabel(card)
  try {
    const host = new URL(card.url).hostname.replace(/^www\./, '')
    const platform = PLATFORMS.find(([domain]) => host === domain || host.endsWith(`.${domain}`))
    if (platform && !label.toLowerCase().includes(platform[1].toLowerCase())) {
      return `${label} · ${platform[1]}`
    }
  } catch {
    // Unparsable URL: the bare label is all we have.
  }
  return label
}

/** Extract a YouTube video id for embedding; null for non-video urls. */
export function youtubeVideoId(url: string): string | null {
  const match = url.match(
    /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|live\/|embed\/)|youtu\.be\/)([\w-]{6,})/,
  )
  return match ? match[1] : null
}

/** The publication to display for a card: the stored origin (feed titles pass
 * through; domains become brand names), else the URL's brand, else collector. */
export function originLabel(card: SourceCard): string {
  if (card.origin) {
    return looksLikeHost(card.origin) ? brandFromHost(card.origin) : card.origin
  }
  try {
    const host = new URL(card.url).hostname
    if (host) {
      return brandFromHost(host)
    }
  } catch {
    // Not a parsable URL; fall through to the collector name.
  }
  return card.source
}
