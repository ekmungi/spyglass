// Sample-mode data for the secondary pages and the assistant: engines, profile, sources,
// status, watch register and paper search. All names are fictional.
import type {
  Engine,
  PaperResult,
  Profile,
  RadarItem,
  ProfileExamples,
  RadarStatus,
  SourcesResponse,
  TodayStatus,
  WatchEntity,
  WatchResponse,
} from '../api/types'
import { hoursAgo, SECTION_LABELS } from './items'

export const ENGINES: Engine[] = [
  {
    id: 'claude',
    label: 'Claude (subscription)',
    kind: 'cli',
    available: true,
    reason: null,
    models: [
      { id: 'sonnet', label: 'Sonnet' },
      { id: 'opus', label: 'Opus' },
    ],
    default_model: 'sonnet',
    is_default: true,
    enabled: true,
    needs_key: false,
    has_key: false,
    key_source: null,
    base_url: null,
    custom: false,
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    kind: 'api',
    available: true,
    reason: null,
    models: [
      { id: 'deepseek/deepseek-chat', label: 'DeepSeek Chat' },
      { id: 'qwen/qwen-max', label: 'Qwen Max' },
    ],
    default_model: 'deepseek/deepseek-chat',
    is_default: false,
    enabled: true,
    needs_key: true,
    has_key: true,
    key_source: 'env',
    base_url: null,
    custom: false,
  },
  {
    id: 'antigravity',
    label: 'Antigravity (your Google plan)',
    kind: 'cli',
    available: false,
    reason: 'Not signed in on this computer.',
    models: [{ id: 'default', label: 'Default model' }],
    default_model: 'default',
    is_default: false,
    enabled: false,
    needs_key: false,
    has_key: false,
    key_source: null,
    base_url: null,
    custom: false,
  },
  {
    id: 'gemini',
    label: 'Google Gemini API',
    kind: 'api',
    available: false,
    reason: 'No API key saved. Add one in Settings.',
    models: [{ id: 'gemini-flash', label: 'Gemini Flash' }],
    default_model: 'gemini-flash',
    is_default: false,
    enabled: false,
    needs_key: true,
    has_key: false,
    key_source: null,
    base_url: null,
    custom: false,
  },
  {
    id: 'openai',
    label: 'OpenAI',
    kind: 'api',
    available: false,
    reason: 'No API key saved. Add one in Settings.',
    models: [{ id: 'gpt-default', label: 'Default model' }],
    default_model: 'gpt-default',
    is_default: false,
    enabled: false,
    needs_key: true,
    has_key: false,
    key_source: null,
    base_url: null,
    custom: false,
  },
  {
    id: 'local',
    label: 'Local model',
    kind: 'local',
    available: false,
    reason: 'No local model server is running on this computer.',
    models: [],
    default_model: null,
    is_default: false,
    enabled: false,
    needs_key: false,
    has_key: false,
    key_source: null,
    base_url: 'http://localhost:11434/v1',
    custom: true,
  },
]

export const PROFILE: Profile = {
  version: 3,
  statement:
    'Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.',
  sections: Object.entries(SECTION_LABELS).map(([key, label]) => ({ key, label, description: `Sample description for ${label}.` })),
  topics: [
    { name: 'AI in medical imaging', section: 'health' },
    { name: 'Medical robotics', section: 'health' },
    { name: 'AI regulation', section: 'health' },
    { name: 'AI in drug discovery', section: 'industry' },
    { name: 'Agent harnesses, MCP and coding agents', section: 'agents' },
    { name: 'Frontier and open-weight model releases', section: 'models' },
    { name: 'Research from major AI labs', section: 'labs' },
    { name: 'AI industry economics and strategy', section: 'direction' },
  ],
  avoid: ['Consumer gadget deals and reviews', 'Games, puzzles and entertainment', 'Sports', 'Celebrity and lifestyle'],
}

/** Titles shown under "what Spyglass has learned" in the sample profile. */
export const EXAMPLES: ProfileExamples = {
  liked: ['Aster AI releases Aster 4 with a million-token context window', 'A new open dataset for medical imaging research', 'Benchmarking foundation models for medical imaging'],
  disliked: ['The best budget earbuds of the year, ranked', 'Ten puzzle games to play this weekend'],
}

type FeedSeed = [name: string, url: string, hours: number, items: number, error?: string]

const FEED_SEEDS: FeedSeed[] = [
  ['Signal Ledger', 'https://example.org/signal-ledger/feed', 1, 12],
  ['Clinical AI Review', 'https://example.org/clinical-ai-review/rss', 1, 5],
  ['The Agent Notebook', 'https://example.org/agent-notebook/feed', 1, 8],
  ['Medtech Dispatch', 'https://example.org/medtech-dispatch/rss', 2, 6],
  ['Open Weights Weekly', 'https://example.org/open-weights/feed', 1, 3],
  ['Policy & Compute', 'https://example.org/policy-compute/feed', 26, 0, 'The feed returned HTTP 404 for the last three attempts.'],
  ['arXiv: medical imaging', 'https://example.org/arxiv/eess.IV', 3, 31],
]

/** Sources as GET /sources sends them: feeds with fetch status, collectors with their last run. */
export const SOURCES: SourcesResponse = {
  feeds: FEED_SEEDS.map(([name, feedUrl, hours, items, error], index) => ({
    id: index + 1,
    name,
    feed_url: feedUrl,
    kind: 'rss',
    enabled: true,
    last_fetch_status: error ? 'error' : 'ok',
    last_fetch_at: hoursAgo(hours),
    last_error: error ?? null,
    item_count: items,
    added_via: 'manual',
  })),
  collectors: [
    { key: 'rss', label: 'RSS feeds', status: 'ok', detail: '34 new of 61 fetched', last_run: hoursAgo(1), new_items: 34 },
    { key: 'news', label: 'News search for watched names', status: 'ok', detail: '11 new', last_run: hoursAgo(2), new_items: 11 },
    { key: 'hn', label: 'Hacker News front page', status: 'ok', detail: '9 new', last_run: hoursAgo(1), new_items: 9 },
    { key: 'hf_papers', label: 'Community paper picks', status: 'ok', detail: '14 new', last_run: hoursAgo(5), new_items: 14 },
    { key: 'gmail', label: 'Email newsletters and links', status: 'skipped', detail: 'not configured: Gmail address or app password is not set', last_run: hoursAgo(1), new_items: null },
    { key: 'capture', label: 'Links you send in', status: 'ok', detail: '2 new', last_run: hoursAgo(3), new_items: 2 },
    { key: 'fda', label: 'FDA device decisions', status: 'ok', detail: '3 new of 8 found', last_run: hoursAgo(4), new_items: 3 },
  ],
}

/** GET /status as the service sends it: last collection an hour ago, the next brief tomorrow morning. */
export function buildStatus(options: { running?: boolean; lastCollectAt?: string } = {}): RadarStatus {
  const next = new Date()
  next.setDate(next.getDate() + 1)
  next.setHours(6, 30, 0, 0)
  return {
    scheduler_running: true,
    cycle_running: options.running === true,
    last_collect_at: options.lastCollectAt ?? hoursAgo(1),
    next_cycle_at: hoursAgo(-3),
    next_brief_at: next.toISOString(),
    brief_time: '06:30',
    queues: { unassessed: 3, unembedded: 1 },
    items_total: 212,
  }
}

/** The `status` block of GET /today. */
export function buildTodayStatus(day: string, hasToday: boolean): TodayStatus {
  return { today: day, has_today: hasToday, latest_day: hasToday ? day : null, generated_at: hasToday ? new Date().toISOString() : null }
}

type EntitySeed = [name: string, kind: string, category: string, why: string, recentIds: number[]]

const WATCH_SEEDS: EntitySeed[] = [
  ['Endovista', 'company', 'Imaging AI', 'Makes real-time polyp detection software.', [102]],
  ['Lucent Scope', 'company', 'Imaging AI', 'Builds AI-guided endoscopes.', [117]],
  ['Halcyon Surgical', 'company', 'Surgical robotics', 'Supervised autonomy in suturing.', [106]],
  ['Meridian Imaging', 'company', 'Medical imaging', 'Publishes annotated procedure video.', [112]],
  ['Aster AI', 'lab', 'AI labs', 'Frontier model provider.', [101, 119]],
  ['Lumen Labs', 'lab', 'AI labs', 'Research on evaluating model reasoning.', [105, 124]],
  ['Corvid Systems', 'lab', 'AI labs', 'Open-weight models suited to on-premise use.', [107, 126]],
  ['Device regulator (sample)', 'regulator', 'Regulators', 'Guidance on AI device change control.', [140]],
]

/** The sample register as a flat list: followed names first, then the suggestions waiting for a yes. */
export function seedWatch(): WatchEntity[] {
  const followed: WatchEntity[] = WATCH_SEEDS.map(([name, kind, category, why], index) => ({
    id: index + 1,
    name,
    kind,
    category,
    topic: null,
    aliases: [],
    query: `"${name}"`,
    website: `https://example.org/${name.toLowerCase().replace(/[^a-z]+/g, '-')}`,
    status: 'active',
    why,
    added_via: 'seed',
    last_hit_at: hoursAgo(6 + index * 5),
  }))
  const suggested: WatchEntity[] = [
    { id: 20, name: 'Arclight Endoscopy', kind: 'company', category: 'Imaging AI', topic: 'AI in medical imaging', aliases: [], query: '"Arclight Endoscopy"', website: null, status: 'suggested', why: 'Named in two items this week about capsule endoscopy.', added_via: 'discovered', last_hit_at: hoursAgo(30) },
    { id: 21, name: 'Quill Robotics', kind: 'company', category: 'Surgical robotics', topic: 'Medical robotics', aliases: [], query: '"Quill Robotics"', website: null, status: 'suggested', why: 'Announced a soft-tissue robot trial.', added_via: 'discovered', last_hit_at: hoursAgo(50) },
  ]
  return [...followed, ...suggested]
}

/**
 * Shape a flat list as GET /watch does: followed and muted names grouped by category (each with up
 * to three recent items from the sample feed), suggestions apart.
 */
export function groupWatch(entities: WatchEntity[], items: RadarItem[]): WatchResponse {
  const byId = new Map(items.map((item) => [item.id, item]))
  const recentFor = (entity: WatchEntity): RadarItem[] =>
    (WATCH_SEEDS.find((seed) => seed[0] === entity.name)?.[4] ?? [])
      .map((id) => byId.get(id))
      .filter((item): item is RadarItem => Boolean(item))
      .slice(0, 3)
  // The sample's week count is how many recent items an entry has, so the numbers match the rows shown.
  const withRecent = (entity: WatchEntity): WatchEntity => {
    const recent = recentFor(entity)
    return { ...entity, recent, week_count: recent.length }
  }
  const followed = entities.filter((entity) => entity.status !== 'suggested').map(withRecent)
  const categories = Array.from(new Set(followed.map((entity) => entity.category || 'Other'))).map((name) => {
    const members = followed.filter((entity) => (entity.category || 'Other') === name)
    return {
      name,
      entities: members,
      week_count: members.reduce((sum, entity) => sum + (entity.week_count ?? 0), 0),
      paused: members.every((entity) => entity.status === 'muted'),
    }
  })
  return { categories, suggested: entities.filter((entity) => entity.status === 'suggested').map(withRecent) }
}

/** Five plausible papers for a topic typed into Find papers. */
export function buildPapers(topic: string, limit: number): PaperResult[] {
  const subject = topic.trim() || 'medical imaging'
  const titles = [
    `A survey of ${subject}: methods, datasets and open problems`,
    `Benchmarking foundation models for ${subject}`,
    `Label-efficient learning for ${subject} with self-supervision`,
    `Failure modes of deployed systems in ${subject}`,
    `Uncertainty estimation for ${subject} in clinical settings`,
  ]
  return titles.slice(0, Math.max(1, limit)).map((title, index) => ({
    title,
    authors: ['R. Lindqvist', 'M. Okafor', 'S. Tanaka'].slice(0, 2 + (index % 2)),
    published: hoursAgo(24 * (index * 9 + 3)),
    url: `https://example.org/papers/${index + 1}`,
    pdf_url: `https://example.org/papers/${index + 1}.pdf`,
    abstract: `This sample abstract summarises a paper on ${subject}. It describes the question, the data, the main result and its limits in four sentences.`,
    why: index === 0 ? 'A good starting map of the field before reading specific results.' : `Relevant to your interest in medical imaging AI; see the section on ${index % 2 ? 'evaluation' : 'data'}.`,
    signal: index === 1 ? '74 community upvotes' : null,
    item_id: index === 0 ? 113 : null,
  }))
}
