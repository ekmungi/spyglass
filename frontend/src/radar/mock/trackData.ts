// Sample-mode data for "follow more like this": suggestions read from a sample article, similar
// items, and the topics already followed. Pure functions only; the routes live in tracks.ts.
import type { RadarItem, Track, TrackKind, TrackSuggestion } from '../api/types'
import { hoursAgo, SECTION_LABELS } from './items'

/** Topic phrases offered for each section when an article names nothing more specific. */
const SECTION_TOPICS: Record<string, string[]> = {
  models: ['Long-context models', 'Open-weight vision models', 'Language model pricing'],
  labs: ['Model evaluation methods', 'Medical foundation models', 'Robotics research'],
  agents: ['Agent harnesses', 'Memory for coding agents', 'Agent permissions'],
  health: ['Real-time polyp detection', 'Imaging AI regulation', 'Surgical video AI'],
  industry: ['AI in hospital operations', 'AI drug design', 'Supply-chain agents'],
  direction: ['AI compute costs', 'AI policy and regulation', 'Inference economics'],
}

/** A realistic reply for one sample article, shaped like a real reading of it. */
const FIXTURES: Record<number, Array<[string, string, TrackKind, string]>> = {
  102: [
    ['Endovista', '"Endovista"', 'organisation', 'The company named in the headline.'],
    ['Polyp detection clearance', 'polyp detection FDA clearance', 'topic', 'The regulatory step this article reports.'],
    ['Second-generation endoscopy AI', 'second-generation endoscopy AI detector', 'topic', 'What changed in the cleared update.'],
    ['Meridian Imaging', '"Meridian Imaging"', 'organisation', 'Another endoscopy company in your feed this week.'],
    ['Imaging AI', 'endoscopy artificial intelligence', 'topic', 'The wider field the article belongs to.'],
  ],
}

/** The leading proper name of a headline ("Aster AI", "Kestrel"), or null when it starts with a common word. */
function leadingName(headline: string): string | null {
  const match = /^([A-Z][\w&-]+(?:\s+(?:AI|Labs|Systems|Surgical|Therapeutics|Logistics|Imaging))?)\s+\p{Ll}/u.exec(headline)
  return match ? match[1] : null
}

/** Whether a query is already followed (compared without case or quote marks). */
function followed(query: string, tracks: readonly Track[]): boolean {
  const plain = (text: string) => text.toLowerCase().replace(/["']/g, '').trim()
  return tracks.some((track) => plain(track.query) === plain(query))
}

/** Suggestions for one sample item, a mix of organisations and topics, flagged when already followed. */
export function suggestionsFor(item: RadarItem, tracks: readonly Track[]): TrackSuggestion[] {
  const sectionKey = item.section || 'direction'
  const sectionLabel = item.section_label || SECTION_LABELS[sectionKey] || ''
  const lines: Array<[string, string, TrackKind, string]> = FIXTURES[item.id] ?? []
  if (lines.length === 0) {
    const name = item.kind === 'paper' ? null : leadingName(item.headline)
    if (name) lines.push([name, `"${name}"`, 'organisation', 'The organisation this article is about.'])
    const topics = SECTION_TOPICS[sectionKey] ?? SECTION_TOPICS.direction
    topics.slice(0, 3).forEach((topic, index) =>
      lines.push([topic, topic.toLowerCase(), 'topic', index === 0 ? 'The main subject of this article.' : 'Closely related to what this article covers.']),
    )
  }
  return lines.map(([label, query, kind, why]) => ({
    label,
    query,
    kind,
    section: sectionKey,
    section_label: sectionLabel,
    why,
    already_followed: followed(query, tracks),
  }))
}

/** Up to eight items from the same section (or the top of the feed), never the item itself. */
export function similarTo(item: RadarItem, items: readonly RadarItem[]): RadarItem[] {
  const pool = items.filter((other) => other.id !== item.id && other.tier !== 'out')
  const sameSection = pool.filter((other) => item.section !== '' && other.section === item.section)
  return (sameSection.length >= 3 ? sameSection : [...sameSection, ...pool.filter((other) => !sameSection.includes(other))]).slice(0, 8)
}

/** The few items whose headline mentions a word of the query: what a topic's recent finds would be. */
export function recentFor(query: string, items: readonly RadarItem[]): RadarItem[] {
  const words = query
    .toLowerCase()
    .replace(/["']/g, ' ')
    .split(/\s+/)
    .filter((word) => word.length > 3)
  return items
    .filter((item) => item.tier !== 'out' && words.some((word) => item.headline.toLowerCase().includes(word)))
    .slice(0, 3)
}

/** The two topics the sample register starts with. */
export function seedTracks(items: readonly RadarItem[]): Track[] {
  const make = (id: number, label: string, query: string, section: string, hours: number, lastNew: number): Track => ({
    id,
    label,
    query,
    section,
    section_label: SECTION_LABELS[section] ?? '',
    kind: 'topic',
    active: true,
    created_at: hoursAgo(72),
    from_item_id: null,
    last_run_at: hoursAgo(hours),
    last_new: lastNew,
    recent: recentFor(query, items),
  })
  return [
    make(1, 'Real-time polyp detection', 'real-time polyp detection', 'health', 3, 2),
    make(2, 'Agent harnesses', 'agent harnesses', 'agents', 3, 0),
  ]
}
