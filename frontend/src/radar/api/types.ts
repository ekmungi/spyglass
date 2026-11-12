// TypeScript shapes for every radar endpoint under /api/radar (items, briefs, assistant,
// filing queue, profile, sources, watch, papers). Fields marked optional are ones the backend may omit.

import type { FiledInfo } from './claudeTypes'

/* ---------- Items ---------- */

export type ItemSource =
  | 'rss'
  | 'raindrop'
  | 'capture'
  | 'news'
  | 'watch'
  | 'hn'
  | 'hf_papers'
  | 'newsletter'
  | 'manual'
  | (string & {})

export type ItemKind =
  | 'news'
  | 'release'
  | 'research'
  | 'paper'
  | 'post'
  | 'video'
  | 'regulatory'
  | 'tool'
  | 'opinion'

export const ITEM_KINDS: readonly ItemKind[] = [
  'news',
  'release',
  'research',
  'paper',
  'post',
  'video',
  'regulatory',
  'tool',
  'opinion',
]

export type Tier = 'top' | 'notable' | 'skim' | 'out' | 'unjudged'

/** A profile section key ("models", "health" …); '' when the item has not been judged. */
export type SectionKey = string

export type Vote = 'more' | 'less' | null

export interface ItemState {
  saved: boolean
  opened: boolean
  vote: Vote
  from_user: boolean
  captured_via: string | null
  vault_path: string | null
  /** The reader's own note on a link they sent; the service does not return it yet. */
  note?: string | null
}

export interface RadarItem {
  id: number
  title: string
  headline: string
  url: string
  source: ItemSource
  origin: string
  published_at: string | null
  fetched_at: string
  kind: ItemKind
  section: SectionKey
  section_label: string
  tier: Tier
  score: number | null
  why: string | null
  key_points: string[]
  entities: string[]
  signal: string | null
  state: ItemState
  has_reader: boolean
  /** The reader's own note, if the service ever returns it at item level. */
  note?: string | null
  /** Where the reader's own Claude Code session filed this item; absent or null until it has. */
  filed?: FiledInfo | null
  /** "waiting" while the item is in the To file queue; null or absent otherwise. */
  filing?: 'waiting' | null
}

export type ReaderKind = 'article' | 'paper' | 'pdf' | 'video' | 'email' | 'note'
export type ReaderStatus = 'ok' | 'pending' | 'failed'

export interface ReaderDoc {
  kind: ReaderKind
  html: string
  title: string | null
  byline: string | null
  site: string | null
  lead_image: string | null
  word_count: number
  source_url: string | null
  alt_url: string | null
  status: ReaderStatus
  error: string | null
  /** Pages of a PDF, when the service knows it; it does not return this yet. */
  page_count?: number | null
  /** True for a subscriber-only preview: readable (status "ok") but not the whole article. */
  partial?: boolean
  /** One plain sentence to show above a partial document. */
  notice?: string | null
}

export interface StorySource {
  item_id: number
  name: string
  url: string
}

export interface ThreadSummary {
  id: number
  title: string
  updated_at: string
}

export interface ItemDetail extends RadarItem {
  summary: string | null
  /** The reader's own words about a link they sent in. */
  user_note?: string | null
  reader: ReaderDoc | null
  related: RadarItem[]
  story_sources: StorySource[]
  threads: ThreadSummary[]
}

export interface FeedQuery {
  section?: string
  kind?: string
  /** 'all' includes items judged out; a tier name narrows to that tier. */
  tier?: string
  saved?: boolean
  from_user?: boolean
  /** Only items filed into the vault by the reader's Claude Code session. */
  filed?: boolean
  /** 'waiting' limits the feed to the To file queue. */
  filing?: 'waiting'
  /** Top and notable items of the last 7 days never opened, saved or filed; one page ordered by score. */
  missed?: boolean
  /** Items this week from any followed name of a Watch group (the number on the group's heading). */
  watch_group?: string
  q?: string
  before?: string
  limit?: number
}

export interface FeedPage {
  items: RadarItem[]
  next_before: string | null
  total: number
}

/** A feed item with how close it is to the text or item it was matched against (0 to 1). */
export interface RelatedItem extends RadarItem {
  match: number
}

/** GET /feed/related: items close to a text or to an item, best first. */
export interface RelatedResponse {
  items: RelatedItem[]
  /** What was asked: the text, or the item (with its headline, for the chip). */
  query: { text?: string; item_id?: number; headline?: string }
}

export type SignalKind = 'open' | 'dwell' | 'expand' | (string & {})

export interface SignalBody {
  kind: SignalKind
  value: string | null
}

/* ---------- Briefs ---------- */

export type BriefSectionKey = 'top' | 'watch' | 'notable' | 'papers' | 'from_you' | 'skim'

/** A watched organisation a watch-list story is about. */
export interface StoryWatch {
  name: string
  category: string
}

export interface Story {
  id: string
  item_id: number
  headline: string
  why: string | null
  section: SectionKey
  section_label: string
  kind: ItemKind
  score: number | null
  signal: string | null
  entities: string[]
  published_at: string | null
  from_user: boolean
  source_count: number
  sources: StorySource[]
  state: ItemState
  /** Present on watch-list stories: the watched organisation(s) the story is about. */
  watch?: StoryWatch[]
}

export interface BriefSection {
  key: BriefSectionKey
  title: string
  note: string | null
  stories: Story[]
}

export interface BriefDoc {
  day: string
  generated_at: string
  opening: string
  quiet: boolean
  read_minutes: number
  collected: number
  filtered_out: number
  sections: BriefSection[]
  /** True when the brief was made with part of the judging missing (for example the AI was unavailable). */
  degraded?: boolean
  /** How many collected items were not judged yet. */
  unjudged?: number
  /** One plain sentence about a degraded brief, shown quietly under the opening. */
  notice?: string | null
}

/** GET /status: scheduler state and queue sizes; every field optional because the backend may omit keys. */
export interface RadarStatus {
  scheduler_running?: boolean
  /** True while a collection and assessment cycle is running. */
  cycle_running?: boolean
  last_collect_at?: string | null
  next_cycle_at?: string | null
  next_brief_at?: string | null
  next_capture_poll_at?: string | null
  brief_time?: string
  timezone?: string
  collect_hours?: number
  queues?: { unassessed?: number; unembedded?: number }
  items_total?: number
  [key: string]: unknown
}

/** The `status` block GET /today sends beside the brief. */
export interface TodayStatus {
  today?: string
  has_today?: boolean
  latest_day?: string | null
  generated_at?: string | null
}

export interface TodayResponse {
  brief: BriefDoc | null
  days: string[]
  /** Days of the last week, today's excluded, whose brief was never opened; newest first. */
  unopened_days?: string[]
  status: TodayStatus
  /** One line on background filing for under the masthead; null or absent when there is nothing to say. */
  filing?: import('./filingTypes').FilingSummary | null
}

/* ---------- Assistant ---------- */

export interface EngineModel {
  id: string
  label: string
}

export interface Engine {
  id: string
  label: string
  kind: string
  available: boolean
  reason: string | null
  models: EngineModel[]
  default_model: string | null
  /** The engine preselected in the assistant drop-down. */
  is_default?: boolean
  enabled?: boolean
  needs_key?: boolean
  has_key?: boolean
  /** Where the key comes from (for example "keyring" or "env"); never the key itself. */
  key_source?: string | null
  base_url?: string | null
  /** True for an engine the reader added (an OpenAI-compatible endpoint). */
  custom?: boolean
}

export interface EngineUpdate {
  enabled?: boolean
  api_key?: string
  base_url?: string
  models?: EngineModel[]
}

export interface Thread {
  id: number
  item_id: number | null
  brief_day: string | null
  title: string
  engine: string | null
  model: string | null
  created_at?: string
  updated_at: string
}

export type AssistRole = 'user' | 'assistant'

/** Preset actions the server knows how to prompt for. */
export type AssistAction = 'explain' | 'relevance' | 'colleagues' | 'linkedin' | 'blog' | 'projects' | 'feed_week' | 'feed_themes'

/** An item the assistant was shown for a question about the feed; answers cite it as [#id]. */
export interface RetrievedItem {
  id: number
  headline: string
}

export interface AssistMessage {
  id: number
  role: AssistRole
  content: string
  selection: string | null
  action: AssistAction | null
  engine: string | null
  model: string | null
  error: string | null
  created_at: string
}

export interface ThreadWithMessages {
  thread: Thread
  messages: AssistMessage[]
  /** Only for the conversation about the feed: the items its answers can cite. */
  retrieved?: RetrievedItem[]
}

export interface CreateThreadBody {
  item_id?: number
  brief_day?: string
  /** 'feed' (or no target at all) is the conversation about the whole feed. */
  scope?: 'feed'
  /** Start a fresh thread instead of returning the latest one for the target. */
  new?: boolean
}

export interface SendMessageBody {
  /** May be '' when `action` is set; the server then writes the prompt for the preset. */
  content: string
  selection?: string
  action?: AssistAction
  engine?: string
  model?: string
}

export type StreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; message_id: number; retrieved?: RetrievedItem[] }
  | { type: 'error'; message: string }

export type * from './claudeTypes'
export type * from './filingTypes'
export type * from './importTypes'
export type * from './pageTypes'
export type * from './trackTypes'
export type * from './watchTypes'
