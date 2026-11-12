// Shapes for "find similar and start tracking": the suggestions read from an article or a link,
// and the followed topics (tracks) the service searches for every day.
import type { RadarItem, SectionKey } from './types'

export type TrackKind = 'topic' | 'organisation' | 'person' | 'product'

/** One thing worth following, proposed from an article. */
export interface TrackSuggestion {
  label: string
  /** The search query the service would run each day. */
  query: string
  kind: TrackKind
  section: SectionKey
  section_label: string
  /** One short sentence on why this came out of the article. */
  why: string
  already_followed: boolean
}

/** POST /items/{id}/track/suggest and POST /track/suggest; `item` is present for the address form. */
export interface TrackSuggestResponse {
  /** 'basic' when no AI model was available and the suggestions came from simple rules. */
  mode?: 'ai' | 'basic'
  suggestions: TrackSuggestion[]
  similar: RadarItem[]
  item?: RadarItem
}

/** A followed topic as GET /tracks lists it. */
export interface Track {
  id: number
  label: string
  query: string
  section: SectionKey
  section_label: string
  kind: TrackKind
  active: boolean
  created_at: string
  from_item_id: number | null
  last_run_at: string | null
  last_new: number
  recent: RadarItem[]
  /** Whether following it also added the topic to the reader's profile topics. */
  topic_added?: boolean
}

export interface TracksResponse {
  tracks: Track[]
}

export interface TrackCreateBody {
  label: string
  query: string
  section: SectionKey
  kind: TrackKind
  from_item_id?: number
}

/** POST /tracks answers the new track plus how many items its first search found. */
export interface TrackCreated extends Track {
  new_items: number
}

export interface TrackPatchBody {
  label?: string
  query?: string
  section?: SectionKey
  active?: boolean
}
