// embed: turns a video address into the address of an embeddable player, but only for a short list
// of known player origins. Anything else gets no player (the reader then offers "Open original").
import { isMockMode } from '../api/transport'

/** The only address prefixes a player iframe may load. */
export const PLAYER_PREFIXES: readonly string[] = [
  'https://www.youtube-nocookie.com/embed/',
  'https://www.youtube.com/embed/',
  'https://player.vimeo.com/video/',
]

/** True when `candidate` starts with one of the allowed player prefixes. */
function isAllowedPlayer(candidate: string): boolean {
  return PLAYER_PREFIXES.some((prefix) => candidate.startsWith(prefix) && candidate.length > prefix.length)
}

/**
 * Turn a video page address into an embeddable player address, or null when there is no safe
 * player for it. The inline `data:text/html` stand-in player is accepted only in sample mode.
 */
export function embedUrl(url: string | null | undefined, sampleMode: boolean = isMockMode()): string | null {
  if (!url) return null
  if (url.startsWith('data:text/html')) return sampleMode ? url : null
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null
  if (parsed.username || parsed.password) return null
  const host = parsed.hostname.replace(/^www\.|^m\./, '')
  let player: string | null = null
  if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
    if (parsed.pathname.startsWith('/embed/')) {
      const origin = host === 'youtube.com' ? 'https://www.youtube.com' : 'https://www.youtube-nocookie.com'
      player = `${origin}${parsed.pathname}${parsed.search}`
    } else {
      const id = parsed.searchParams.get('v') ?? (parsed.pathname.startsWith('/shorts/') ? parsed.pathname.split('/')[2] : null)
      player = id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` : null
    }
  } else if (host === 'youtu.be') {
    const id = parsed.pathname.slice(1)
    player = id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` : null
  } else if (host === 'vimeo.com') {
    const id = parsed.pathname.split('/').filter(Boolean)[0]
    player = id && /^\d+$/.test(id) ? `https://player.vimeo.com/video/${id}` : null
  } else if (host === 'player.vimeo.com' && parsed.pathname.startsWith('/video/')) {
    player = `https://player.vimeo.com${parsed.pathname}${parsed.search}`
  }
  // Final gate: whatever was built must still sit under an allowed player prefix.
  return player && isAllowedPlayer(player) ? player : null
}
