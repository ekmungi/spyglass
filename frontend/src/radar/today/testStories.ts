// Story fixtures for the Today tests: plain stories with numbered headlines, so a test can tell which
// stories a page shows by their headlines alone.
import type { Story } from '../api/types'

/** A story for item `id` with the headline "Story <id>"; `over` replaces any field. */
export function makeStory(id: number, over: Partial<Story> = {}): Story {
  return {
    id: `s-${id}`,
    item_id: id,
    headline: `Story ${id}`,
    why: `Why story ${id} matters.`,
    section: 'models',
    section_label: 'Models',
    kind: 'news',
    score: 80,
    signal: null,
    entities: [],
    published_at: null,
    from_user: false,
    source_count: 1,
    sources: [{ item_id: id, name: 'Signal Ledger', url: `https://example.org/${id}` }],
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    ...over,
  }
}

/** `count` stories whose item ids run upwards from `first`. */
export function makeStories(count: number, first: number): Story[] {
  return Array.from({ length: count }, (_, offset) => makeStory(first + offset))
}
