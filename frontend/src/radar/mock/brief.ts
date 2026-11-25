// Sample-mode briefs: today's brief with every section, plus a shorter brief for earlier days.
import type { BriefDoc, BriefSection, BriefSectionKey, RadarItem, Story, StorySource } from '../api/types'

/** Local calendar day (YYYY-MM-DD) `offset` days before today. */
export function localDay(offset = 0): string {
  const date = new Date()
  date.setDate(date.getDate() - offset)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

// Extra outlets reporting the same event, so the brief can show "Publication · Publication · +3".
const EXTRA_SOURCES: Record<number, string[]> = {
  101: ['Open Weights Weekly', 'Frontier Notes', 'Industry Brief Daily', 'Policy & Compute'],
  102: ['Clinical AI Review', 'Industry Brief Daily'],
  103: ['Open Weights Weekly'],
  104: ['Medtech Dispatch', 'Signal Ledger'],
  117: ['Industry Brief Daily'],
  140: ['Clinical AI Review'],
}

// The watched organisation behind each sample watch-list story (names match the sample register).
const WATCH_FOR: Record<number, { name: string; category: string }[]> = {
  102: [{ name: 'Endovista', category: 'Imaging AI' }],
  117: [{ name: 'Lucent Scope', category: 'Imaging AI' }],
  106: [{ name: 'Halcyon Surgical', category: 'Surgical robotics' }],
  112: [{ name: 'Meridian Imaging', category: 'Medical imaging' }],
}

// Today's sample brief was made while a few collected items still waited to be judged, so sample
// mode shows the closing line about them (the number matches the sample status's unassessed queue).
const UNJUDGED = 3

/** Turn an item into a brief Story, attaching any extra sources reporting the same event. */
export function storyFor(item: RadarItem): Story {
  const extras = EXTRA_SOURCES[item.id] ?? []
  const sources: StorySource[] = [
    { item_id: item.id, name: item.origin, url: item.url },
    ...extras.map((name, index) => ({ item_id: 900 + item.id * 10 + index, name, url: `https://example.org/${index}` })),
  ]
  return {
    id: `s-${item.id}`,
    item_id: item.id,
    headline: item.headline,
    why: item.why,
    ...(item.what ? { what: item.what } : {}),
    section: item.section,
    section_label: item.section_label,
    kind: item.kind,
    score: item.score,
    signal: item.signal,
    entities: item.entities,
    published_at: item.published_at,
    from_user: item.state.from_user,
    source_count: sources.length,
    sources,
    state: item.state,
    ...(WATCH_FOR[item.id] ? { watch: WATCH_FOR[item.id] } : {}),
  }
}

// Each section's picked stories (`ids`) and, for today's brief, its unpicked ones (`more`: judged
// for the section and left out, best first) with the number judged (`pool`), as a real brief has
// them. The top section, the watch list, Worth knowing, Papers and Skim each need a second page, and
// show the ring of an unpicked story. From you never gets unpicked stories (the service offers left
// over stories to every section but that one), so its `more` is empty and it fits on one page.
const LAYOUT: { key: BriefSectionKey; title: string; note: string | null; ids: number[]; more?: number[]; pool?: number }[] = [
  { key: 'top', title: 'Top stories', note: '3 picked from 96', ids: [101, 104, 103], more: [141, 142, 143], pool: 96 },
  { key: 'watch', title: 'On your watch list', note: null, ids: [102, 117], more: [106, 112], pool: 4 },
  { key: 'notable', title: 'Worth knowing', note: null, ids: [140, 105, 107, 108, 109, 120], more: [110, 111], pool: 18 },
  { key: 'papers', title: 'Papers', note: '4 of 31 new papers', ids: [113, 114, 115, 116], more: [144, 145], pool: 31 },
  { key: 'from_you', title: 'From you', note: null, ids: [131, 132], more: [], pool: 2 },
  { key: 'skim', title: 'Skim', note: null, ids: [119, 118, 121, 122, 123, 124, 125, 126, 127, 128], more: [129, 130, 133, 139], pool: 41 },
]

/** The stories for `ids`, skipping any id with no sample item. */
function storiesFor(ids: number[], byId: Map<number, RadarItem>): Story[] {
  return ids
    .map((id) => byId.get(id))
    .filter((item): item is RadarItem => Boolean(item))
    .map(storyFor)
}

/**
 * Build today's full brief from the current sample items (so read, saved and vote state carry over);
 * it carries the line about items not judged yet. An earlier day's brief (`short`) has two stories per
 * section, no unpicked stories and no such line, like a complete brief composed before unpicked
 * stories were stored.
 */
export function buildBrief(items: RadarItem[], day: string, short = false): BriefDoc {
  const byId = new Map(items.map((item) => [item.id, item]))
  const sections: BriefSection[] = LAYOUT.map((section) => ({
    key: section.key,
    title: section.title,
    note: section.note,
    stories: storiesFor(section.ids.slice(0, short ? 2 : undefined), byId),
    ...(!short && section.more ? { more: storiesFor(section.more, byId), pool: section.pool } : {}),
  }))
    // Earlier days drop two sections, which also exercises "empty sections are omitted".
    .filter((section) => !short || (section.key !== 'watch' && section.key !== 'from_you'))
    .filter((section) => section.stories.length > 0)
  return {
    day,
    generated_at: new Date().toISOString(),
    opening: short
      ? 'A quieter day: one notable model update and a handful of agent-tooling releases.'
      : 'Aster AI made long documents cheap to process in one pass, and two imaging companies moved: one won a clearance, the other raised money. The rest is mostly agent tooling and a useful benchmark for surgical video.',
    quiet: short,
    read_minutes: short ? 3 : 6,
    collected: short ? 164 : 212,
    filtered_out: short ? 151 : 179,
    sections,
    ...(short
      ? {}
      : {
          degraded: true,
          unjudged: UNJUDGED,
          notice: `${UNJUDGED} collected items are still waiting to be judged, so a story may be missing from today's selection.`,
        }),
  }
}
