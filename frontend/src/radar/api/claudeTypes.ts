// Shapes for "Open in Claude Code", the projects the assistant may mention, and the privacy
// overview. The service for these is finished in parallel; a 404 means "not in this copy yet".

/* ---------- Open in Claude Code ---------- */

/** What Claude Code is asked to do with an item. */
export type ClaudeIntent = 'file' | 'discuss' | 'custom'

/** How an item is filed when the reader wants to say. */
export type ClaudeKind = 'resource' | 'to explore' | 'learning' | 'feature idea'

/** Body of POST /items/{id}/claude/preview and /claude/open (the same for both). */
export interface ClaudeRequest {
  intent: ClaudeIntent
  /** The project to file into; absent lets Claude propose one. */
  project?: string
  as_kind?: ClaudeKind
  /** The reader's own request, for `intent: "custom"`. */
  custom?: string
}

/** Reply of POST /items/{id}/claude/preview: exactly what would be sent, and whether it can be. */
export interface ClaudePreview {
  text: string
  vault: string | null
  available: boolean
  reason: string | null
  /** A project the reader named in their own note on the item. */
  project_hint?: { name: string; source: 'note' } | null
}

/** Reply of POST /items/{id}/claude/open. */
export interface ClaudeOpened {
  opened: boolean
  /** "link" when the request travelled in the link itself, "handoff" when the session fetches it. */
  delivery?: 'link' | 'handoff'
}

/** Where an item was filed, as reported back by the reader's own Claude Code session. */
export interface FiledInfo {
  path: string
  project: string | null
  at: string
}

/* ---------- Projects the assistant may mention ---------- */

/** One project of the reader's vault; `description` is the only thing about it the AI may see. */
export interface ProjectRow {
  name: string
  description: string
  in_vault: boolean
}

/** GET /projects. */
export interface ProjectsResponse {
  projects: ProjectRow[]
}

/** PUT /projects body: the projects the reader chose to describe. */
export interface ProjectsBody {
  projects: { name: string; description: string }[]
}

/* ---------- Privacy overview ---------- */

/** One outside place Spyglass connects to. */
export interface PrivacyDestination {
  name: string
  host: string
  purpose: string
  what_is_sent: string
  carries_secret: boolean
  enabled: boolean
}

/** The four switches of the Privacy section; saved through PATCH /api/settings under these names. */
export interface PrivacySwitches {
  privacy_send_examples: boolean
  privacy_proxy_images: boolean
  jina_enabled: boolean
  privacy_allow_bot_checks: boolean
}

export type PrivacySwitchKey = keyof PrivacySwitches

/** GET /privacy/outbound. */
export interface PrivacyOutbound {
  model_provider: { name: string; host: string }
  /** The profile text exactly as it goes to the AI. */
  profile_block: string
  example_titles: { liked: string[]; disliked: string[] }
  destinations: PrivacyDestination[]
  switches: PrivacySwitches
}
