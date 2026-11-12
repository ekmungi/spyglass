// Shapes for the secondary pages' endpoints (profile, sources, watch, papers). Re-exported
// from ./types, so import them from there.
import type { RadarItem, SectionKey } from './types'

/* ---------- Profile ---------- */

export interface ProfileSection {
  key: SectionKey
  label: string
  description: string
}

export interface ProfileTopic {
  name: string
  section: SectionKey
}

export interface Profile {
  version: number
  statement: string
  sections: ProfileSection[]
  topics: ProfileTopic[]
  avoid: string[]
  [key: string]: unknown
}

/** Titles Spyglass derived from the reader's votes and saves, shown as "what it has learned". */
export interface ProfileExamples {
  liked: string[]
  disliked: string[]
}

/** What GET and PUT /profile return: the profile document and the learned examples beside it. */
export interface ProfileResponse {
  profile: Profile
  examples: ProfileExamples
}

/* ---------- Sources ---------- */

/** One subscribed feed as GET /sources lists it. */
export interface FeedSource {
  id: number
  name: string
  feed_url: string
  /** 'rss' or 'youtube'. */
  kind: string
  enabled: boolean
  /** 'ok' or 'error' after a fetch; null before the first one. */
  last_fetch_status: string | null
  last_fetch_at: string | null
  last_error: string | null
  item_count: number
  added_via: string
}

/** One collector (news search, Hacker News, email …) with its last run. */
export interface CollectorStatus {
  key: string
  label: string
  /** 'ok', 'error' or 'skipped' (not configured) after a run. */
  status: string
  /** One-line outcome or error text from the last run. */
  detail: string | null
  last_run: string | null
  new_items: number | null
}

export interface SourcesResponse {
  feeds: FeedSource[]
  collectors: CollectorStatus[]
}

export interface CaptureBody {
  url: string
  note?: string
}

/** POST /collect starts the run in the background and answers at once. */
export interface CollectResult {
  started: boolean
}

/* ---------- Watch ---------- */

export type WatchKind = 'company' | 'lab' | 'regulator' | 'person' | 'publication'
export type WatchStatus = 'active' | 'suggested' | 'muted'

export interface WatchEntity {
  id: number
  name: string
  kind: WatchKind | (string & {})
  category: string
  topic: string | null
  aliases: string[]
  /** The news search the daily check runs for this name. */
  query?: string | null
  website: string | null
  status: WatchStatus
  why: string | null
  added_via: 'seed' | 'discovered' | 'user' | (string & {})
  last_hit_at: string | null
  recent?: RadarItem[]
  /** Items this name brought into the Feed in the last 7 days. */
  week_count?: number
}

export interface WatchCategory {
  name: string
  entities: WatchEntity[]
  /** Items the whole group brought into the Feed in the last 7 days. */
  week_count?: number
  /** True when every name in the group is muted. */
  paused?: boolean
}

export interface WatchResponse {
  categories: WatchCategory[]
  suggested: WatchEntity[]
}

export interface WatchCreateBody {
  name: string
  kind: string
  category: string
  query?: string
}

export interface WatchPatchBody {
  name?: string
  kind?: string
  category?: string
  query?: string | null
  status?: WatchStatus
}

export interface WatchDiscoverResponse {
  suggested: WatchEntity[]
  /** Names the model proposed that could not be verified. */
  rejected?: number
  /** Names the model proposed that were already on the list. */
  already_known?: number
}

/* ---------- Papers ---------- */

export interface PaperResult {
  title: string
  authors: string[]
  published: string | null
  url: string
  pdf_url: string | null
  abstract: string
  why: string | null
  signal: string | null
  item_id: number | null
}

export interface PapersResponse {
  papers: PaperResult[]
  /** "degraded" when a source or the ranking failed and the list may be incomplete; "empty" when nothing matched. */
  status?: 'ok' | 'degraded' | 'empty'
  /** One plain sentence about a degraded or empty search, or null. */
  notice?: string | null
}
