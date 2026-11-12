// Shapes for the To file queue: items the reader marked for filing in their notes vault. One
// Claude Code session later files the whole queue through the vault's own skills.
import type { ClaudeKind } from './claudeTypes'
import type { RadarItem } from './types'

/** The kinds of note the reader can ask for; the same four as the Claude Code dialog used. */
export type FilingKind = ClaudeKind

/** What the reader chose when queuing an item. Every field is optional; the kind defaults to resource. */
export interface FilingChoice {
  kind?: FilingKind
  /** One of the reader's listed projects; absent leaves the project to the filing session. */
  project?: string
  /** A one-line note for the filing session. */
  note?: string
}

/** Reply of POST /items/{id}/file and DELETE /items/{id}/file. */
export interface FilingResult {
  item_id: number
  filing: 'waiting' | null
  /** How many items are waiting now. */
  count: number
}

/** One waiting item with the choices stored for it. */
export interface FilingEntry {
  item: RadarItem
  kind: FilingKind
  project: string | null
  note: string
  requested_at: string
}

/** GET /filing. */
export interface FilingQueue {
  count: number
  waiting: FilingEntry[]
}

/* ---------- Background filing run ---------- */

/** The background filing mode: only File now, file first and ask after, or plan first. */
export type FilingMode = 'off' | 'auto' | 'plan_first'

/** What the last background run did. */
export interface FilingLastRun {
  kind: 'file' | 'plan' | null
  started_at: string | null
  finished_at: string | null
  result: 'ok' | 'partial' | 'stopped' | null
  reason: string | null
  /** The stop reason in plain words ("Obsidian was closed"), or null. */
  reason_text: string | null
  detail: string | null
  filed: number
  asked: number
  proposed: number
  /** The run's cost at list price, as Claude Code reported it. */
  cost_usd?: number | null
  /** Tool calls the run tried and was refused ("Bash: …"), at most 20. */
  refused?: string[]
}

/** The background run's status: the mode, whether one runs now, the last run and one plain line. */
export interface FilingStatus {
  /**
   * True only when the reader has named their own Claude Code filing skills in their local settings.
   * Everything about filing stays hidden unless this is true; a missing field counts as false.
   */
  configured?: boolean
  /**
   * True only when this version can file in the background. False in this release: filing runs when
   * the reader clicks File now. A missing field counts as false.
   */
  background_available?: boolean
  mode: FilingMode
  state: 'idle' | 'running'
  last_run: FilingLastRun | null
  next_retry: string | null
  /** One sentence the view shows as it is. */
  line: string
}

/** One open question on a filed item: the fixed question and its choices ("No project" last). */
export interface FilingQuestion {
  id: number
  item_id: number
  headline: string
  question: string
  options: string[]
  asked_at: string
}

/** One row of a plan-first run's proposal. */
export interface FilingPlanRow {
  id: number
  item_id: number
  headline: string
  becomes: string
  place: string
  name: string
  project: string | null
  unsure: boolean
  reason: string
  decision: 'pending' | 'approved'
  proposed_at: string
}

/** An item filed in the last 14 days. */
export interface FilingRecent {
  item_id: number
  headline: string
  path: string
  project: string | null
  /** True when a background run chose the place because no place was given. */
  best_guess: boolean
  at: string
}

/** GET /filing from a service with background filing (older services send only count and waiting). */
export interface FilingOverview extends FilingQueue {
  status?: FilingStatus
  questions?: FilingQuestion[]
  plan?: FilingPlanRow[]
  recent?: FilingRecent[]
}

/** One answered line of the single Submit. */
export interface FilingAnswer {
  question_id: number
  choice: string
}

/** The brief's one filing line (GET /today `filing`), or null when there is nothing to say. */
export interface FilingSummary {
  line: string
  filed_yesterday: number
  questions: number
  plan: number
}
