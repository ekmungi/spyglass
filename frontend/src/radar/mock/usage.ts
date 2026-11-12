// Sample mode for the usage endpoints: a believable week of use, and figures for any stored answer.
import type { UsageFigures, UsageReport, UsageTotals } from '../api/usageTypes'

function totals(calls: number, fresh: number, written: number, read: number, output: number, cost: number | null): UsageTotals {
  const context = fresh + written + read
  return {
    calls,
    input_tokens: fresh,
    cache_write_tokens: written,
    cache_read_tokens: read,
    output_tokens: output,
    context_tokens: context,
    cached_share: context ? read / context : null,
    cost_usd: cost,
    unreported_calls: 0,
  }
}

const TRIAGE = totals(214, 428, 612_000, 760_000, 98_000, 0.41)
const DIGEST = totals(588, 1_176, 1_240_000, 1_810_000, 211_000, 0.93)
const CHAT = totals(23, 46, 38_000, 210_000, 14_000, 0.12)
const OPENING = totals(7, 14, 9_000, 4_000, 3_000, 0.02)

function sum(...rows: UsageTotals[]): UsageTotals {
  return totals(
    rows.reduce((n, r) => n + r.calls, 0),
    rows.reduce((n, r) => n + r.input_tokens, 0),
    rows.reduce((n, r) => n + r.cache_write_tokens, 0),
    rows.reduce((n, r) => n + r.cache_read_tokens, 0),
    rows.reduce((n, r) => n + r.output_tokens, 0),
    rows.reduce((n, r) => n + (r.cost_usd ?? 0), 0),
  )
}

/** The sample report; the number of days only changes the label, not the figures. */
export function sampleReport(days: number): UsageReport {
  const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 10)
  return {
    days,
    since: new Date(Date.now() - days * 86_400_000).toISOString(),
    totals: sum(TRIAGE, DIGEST, CHAT, OPENING),
    per_day: [2, 1, 0].map((offset) => ({ day: day(offset), ...sum(TRIAGE, DIGEST, CHAT, OPENING) })),
    by_purpose: [
      { purpose: 'chat', ...CHAT },
      { purpose: 'triage', ...TRIAGE },
      { purpose: 'digest', ...DIGEST },
      { purpose: 'brief_opening', ...OPENING },
    ],
    by_model: [{ purpose: 'digest', provider: 'claude_code', model: 'haiku', ...DIGEST }],
    conversations: [{ thread_id: 1, title: 'Explain', item_id: 101, turns: 6, ...CHAT }],
  }
}

/** Figures for a stored answer: every fourth one reads as a condensed conversation. */
export function sampleMessageUsage(messageId: number): UsageFigures {
  return {
    input_tokens: 2,
    cache_write_tokens: 380,
    cache_read_tokens: 12_018,
    output_tokens: 380,
    context_tokens: 12_400,
    cached_share: 12_018 / 12_400,
    model: 'sonnet',
    provider: 'claude_code',
    ...(messageId % 4 === 0 ? { condensed: true } : {}),
  }
}

/** Route /usage and /usage/messages/{id}; null for any other path. */
export function usageRoute(method: string, parts: string[], params: URLSearchParams): Response | null {
  if (method !== 'GET' || parts[0] !== 'usage') return null
  const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (parts.length === 1) return json(sampleReport(Number(params.get('days') ?? 7) || 7))
  if (parts[1] === 'messages') return json(sampleMessageUsage(Number(parts[2])))
  return null
}
