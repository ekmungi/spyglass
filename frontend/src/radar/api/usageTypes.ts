// Shapes of the usage endpoints: GET /usage (the report) and GET /usage/messages/{id} (one answer).

/** Token figures for one model call or one answer; parts the provider did not report are absent. */
export interface UsageFigures {
  input_tokens?: number
  cache_write_tokens?: number
  cache_read_tokens?: number
  output_tokens?: number
  /** The whole prompt: fresh + written to the cache + read from the cache. */
  context_tokens?: number
  /** Share of the prompt that was read from the cache, 0 to 1. */
  cached_share?: number
  cost_usd?: number
  /** The turn started from a short summary of the earlier conversation. */
  condensed?: boolean
  model?: string
  provider?: string
}

/** Totals for one grouping of calls. `cached_share` and `cost_usd` are null when nothing was reported. */
export interface UsageTotals {
  calls: number
  input_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  output_tokens: number
  context_tokens: number
  cached_share: number | null
  cost_usd: number | null
  /** Calls whose provider reported no token figures at all. */
  unreported_calls: number
}

export interface UsageDay extends UsageTotals {
  day: string
}

export interface UsagePurpose extends UsageTotals {
  purpose: string
}

export interface UsageModel extends UsageTotals {
  purpose: string
  provider: string
  model: string
}

export interface UsageConversation extends UsageTotals {
  thread_id: number
  title: string
  item_id: number | null
  turns: number
}

export interface UsageReport {
  days: number
  since: string
  totals: UsageTotals
  per_day: UsageDay[]
  by_purpose: UsagePurpose[]
  by_model: UsageModel[]
  conversations: UsageConversation[]
}
