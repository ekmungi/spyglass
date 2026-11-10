// Shared test fixtures: factories so tests only state what they care about.
import type { Brief, CardData } from '../lib/types'

/** Build a complete CardData with sensible defaults, overridable per test. */
export function makeCard(overrides: Partial<CardData> = {}): CardData {
  return {
    id: 1,
    state: 'new',
    curated: true,
    summary: 'Summary',
    tags: [],
    category: null,
    category_ai: null,
    category_override: false,
    category_confirmed: false,
    category_tier: null,
    category_recommendations: [],
    group: null,
    relevance: null,
    relevance_ai: null,
    relevance_reason: null,
    relevance_override: false,
    // Mirror relevance by default; tests that need a distinct effective value can pass it explicitly.
    effective_relevance: null,
    feedback: null,
    source_tags: [],
    note: null,
    deep_dive_prompt: null,
    briefing_path: null,
    created_at: '2026-06-10T08:00:00Z',
    updated_at: '2026-06-10T08:00:00Z',
    title: 'A card',
    url: 'https://example.test/1',
    source: 'rss',
    origin: null,
    published_at: null,
    ...overrides,
  }
}

/** Build a complete Brief with sensible defaults, overridable per test. */
export function makeBrief(overrides: Partial<Brief> = {}): Brief {
  return {
    id: 1,
    created_at: '2026-07-01T06:00:00Z',
    covers_from: '2026-06-30T06:00:00Z',
    covers_until: '2026-07-01T06:00:00Z',
    item_count: 5,
    low_count: 3,
    title: 'Daily Brief — Jul 1, 2026',
    markdown:
      '# Daily Brief\n\nRead [First card](card:1) and [Second card](card:2). More on [the web](https://example.com).',
    ...overrides,
  }
}
