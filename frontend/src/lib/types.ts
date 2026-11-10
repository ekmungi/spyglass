// Shared API types mirrored from the service's REST serializers.

export type CardState = 'new' | 'reviewed' | 'dismissed' | 'queued' | 'finished'

// Relevance scale from the AI pass; null = not judged yet.
export type Relevance = 'high' | 'medium' | 'low' | 'out'

// Holistic user feedback; null = not rated. Distinct from relevance.
export type Feedback = 'up' | 'down' | null

export interface CardData {
  id: number
  state: CardState
  curated: boolean
  summary: string
  tags: string[]
  category: string | null
  category_ai: string | null
  category_override: boolean
  // Whether the user has confirmed the auto-assigned category.
  category_confirmed: boolean
  // Embedding-derived placement quality: 'tentative' or 'outlier'; null until assessed.
  category_tier: 'tentative' | 'outlier' | null
  // Nearest-category suggestions from the embedding model; empty until assessed.
  category_recommendations: string[]
  group: string | null
  relevance: Relevance | null
  relevance_ai: Relevance | null
  relevance_reason: string | null
  relevance_override: boolean
  // Blended displayed/filterable level: AI value + any override applied. null = unjudged (never scored).
  effective_relevance: Relevance | null
  feedback: Feedback
  source_tags: string[]
  note: string | null
  deep_dive_prompt: string | null
  briefing_path: string | null
  created_at: string
  updated_at: string
  title: string
  url: string
  source: string
  // Where the item came from: feed title (RSS) / site domain (Raindrop).
  // `source` only names the collector; null for items collected before 0.5.
  origin: string | null
  published_at: string | null
}

export interface CardPatch {
  state?: CardState
  note?: string
  deep_dive_prompt?: string
}

// A background full-text fetch job. `queued`/`running` mean the tiered
// acquisition ladder is still going to do work; `done`/`failed` are terminal. `error`
// carries the reason a job RAISED — including `interrupted` for a job the service was
// killed in the middle of. A ladder that merely failed to get text is a `done` job with
// the structured reason on the FulltextResult instead.
export interface FetchJobState {
  job_id: number
  card_id: number
  status: 'queued' | 'running' | 'done' | 'failed'
  error: string | null
}

// Stored full text for the reader pane. markdown is null until fetched.
// The error/tier/type fields carry a legible, structured failure reason
// from the tiered fetch ladder; they are absent/null on older rows and
// on any non-failed status, so the reader falls back to the generic message.
export interface FulltextResult {
  status: 'ok' | 'empty' | 'failed' | 'paywalled' | 'absent'
  markdown: string | null
  // Composed human-readable failure reason, e.g. "blocked at T0 (HTTP 403); T3 (browser) also failed: timeout".
  error?: string | null
  error_class?: string | null
  // Highest fetch-ladder tier reached before giving up, e.g. "T3".
  tier_reached?: string | null
  detected_type?: string | null
  http_status?: number | null
  // The card's most recent fetch job, or null if it has never been fetched.
  // Reading this on mount is what lets a fresh reader pane show a fetch it never saw start;
  // absent on responses from a pre-0.29 service.
  job?: FetchJobState | null
}

// One FTS hit: a card plus the snippet showing where the query matched.
export interface SearchResult extends CardData {
  snippet: string
}

// Result of POST /api/pages: the fetched-and-judged card, plus whether
// it was newly created or the URL was already collected.
export interface AddedPage extends CardData {
  status: 'created' | 'exists'
}

// One find-similar neighbour: a card plus its cosine score (0..1, best first).
export interface ScoredCard extends CardData {
  score: number
}

// A managed category: persists in dropdowns even at count 0.
export interface CategoryInfo {
  name: string
  count: number
}

// One proposed new category from a Recategorize run: a name the clustering
// suggested, the cluster size, its member card ids, and a few example titles for the review UI.
export interface RecatCandidate {
  suggested_name: string
  size: number
  card_ids: number[]
  examples: string[]
}

// GET /api/recategorize payload: the latest run's status plus its candidate categories.
// status: 'none' (never run) | 'running' | 'ok' | 'error'.
export interface RecatResult {
  status: 'none' | 'running' | 'ok' | 'error'
  finished_at?: string | null
  assigned?: number
  candidates: RecatCandidate[]
}

// Editable service settings shown in the Settings tab.
export interface ServiceSettings {
  vault_path: string | null
  feed_note_path: string | null
  interest_note_path: string | null
  preferences_note_path: string | null
  port: number
  fulltext_refresh_hours: number
  relevance_threshold: Relevance
  relevance_model: 'haiku' | 'sonnet'
  // Path to the yt-transcribe CLI for video transcripts; '' = auto-detect.
  yt_transcribe_cmd: string
  // The Slack channel for the paper inbox, without the leading '#'.
  inbox_channel?: string
  // Background jobs: the Claude Code command ('' or null = find it), the time limit per
  // run in minutes, and the vault folder for detailed notes. Absent from an older service.
  claude_command?: string | null
  job_timeout_minutes?: number
  detail_notes_subdir?: string
  // The Obsidian MCP server File it moves notes with, and the address that answers while
  // Obsidian runs.
  obsidian_mcp_server?: string
  obsidian_probe_url?: string
  // The model each background job runs on: an alias (haiku, sonnet, opus, fable) or a full name.
  job_model_prepare?: string
  job_model_file?: string
}

// One pass of the paper inbox, as GET /api/inbox reports it.
export interface InboxRunInfo {
  id: number
  status: 'running' | 'ok' | 'error'
  papers: number
  error: string | null
  started_at: string
  finished_at: string | null
  debrief_path?: string | null
}

// A run that wrote a debrief: how its papers connect.
export interface InboxDebrief {
  run_id: number
  papers: number
  debrief_path: string
  started_at: string
}

// One shared paper in the Inbox tab; its debrief lives in the vault note.
export interface InboxPaper {
  entry_id: number
  card_id: number
  title: string
  url: string
  summary: string
  note_path: string | null
  message_text: string | null
  full_text: boolean
  filed: boolean
  shared: number
  added_at: string
}

export interface InboxData {
  channel: string
  last_run: InboxRunInfo | null
  papers: InboxPaper[]
  debriefs?: InboxDebrief[]
}

// A Daily Brief entry as listed by GET /api/briefs, newest first.
export interface BriefSummary {
  id: number
  created_at: string
  // The collection window this brief covers (ISO timestamps).
  covers_from: string
  covers_until: string
  // Articles summarized in the brief vs. low-relevance items only counted.
  item_count: number
  low_count: number
  // Display title, e.g. "Daily Brief — Jul 3, 2026".
  title: string
}

// A full brief (GET /api/briefs/{id}): summary fields + the rendered markdown.
// Article references inside the markdown use the custom `card:<id>` link scheme.
export interface Brief extends BriefSummary {
  markdown: string
}

// POST /api/briefs/generate result: the briefs composed this run (light
// summaries, newest first), a status, and `held` — how many due days did NOT compose
// this run (e.g. a heavy day the composer paused on). `held` lets the UI
// distinguish "nothing was due" (held 0) from "something is stuck" (held > 0), rather
// than showing the same "nothing to brief" for both.
export interface BriefGenerateResult {
  composed: BriefSummary[]
  status: 'composed' | 'empty'
  held: number
}

export interface RunRow {
  id: number
  source: string
  status: string
  detail: string | null
  started_at: string
  finished_at: string | null
}

// A feed candidate returned by POST /api/feeds/discover.
export interface FeedCandidate {
  feed_url: string
  name: string
  kind: string
  already_subscribed: boolean
}

// Result from POST /api/feeds/discover.
export interface DiscoverResult {
  candidates: FeedCandidate[]
  reason: string | null
  // Machine-readable code (blocked/no_feeds/not_html/too_large/http_error/network_error).
  reason_code?: string | null
}

// A managed RSS/Atom feed. Mirrors the service FeedOut serializer.
export interface FeedData {
  id: number
  feed_url: string
  name: string
  name_overridden: boolean
  kind: string
  enabled: boolean
  last_fetch_status: string | null
  last_fetch_at: string | null
  last_error: string | null
  item_count: number
  added_via: string
}

// The linked Claude session: whether one is linked, since when, its last call to
// Spyglass, and whether a session was opened that has not claimed its link yet.
export interface LinkStatus {
  linked: boolean
  // Linked once, but silent for hours (probably closed); absent from an older service.
  idle?: boolean
  linked_at: string | null
  last_seen: string | null
  waiting: boolean
  // Why there is no link now: ended in Spyglass, or ended when Spyglass closed.
  ended?: 'ended' | 'closed' | null
  // When the oldest new session that has not linked yet was opened.
  waiting_since?: string | null
}

// Background jobs: a hidden Claude run that prepares or files an item's detailed note.
export type JobKind = 'prepare-detail' | 'file-note'
export type JobStatus = 'queued' | 'running' | 'ok' | 'failed' | 'cancelled'

export interface ClaudeJob {
  id: number
  kind: JobKind
  card_id: number
  status: JobStatus
  // The note it wrote, or where it filed it (vault-relative).
  note_path: string | null
  // Claude's one-line report ("Filed to ... because ...").
  message: string | null
  // What a running job is doing now ("Opening Obsidian").
  progress: string | null
  error: string | null
  cost_usd: number | null
  duration_ms: number | null
  num_turns: number | null
  // The model the run used, and how much of the user's Claude limits was used after it (0..1).
  model?: string | null
  usage_five_hour?: number | null
  usage_week?: number | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface CardJobs {
  jobs: ClaudeJob[]
  // The card's note: vault-relative path, and whether it is still unfiled in Brief notes.
  note: { path: string | null; unfiled: boolean }
  // Set while jobs wait for the user's Claude usage limit to reset.
  paused_until?: string | null
}
