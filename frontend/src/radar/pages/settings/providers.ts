// providers: the AIs that can do the daily judging, and how the settings store the order to try them.
// `radar_llm_provider` is the first choice; `radar_llm_fallback` is a comma-separated list of the rest.
import type { EngineRow } from './api'

export interface JudgingProvider {
  /** The value stored in the settings. */
  id: string
  /** The name shown when the engine list does not name it. */
  label: string
  /** Engine ids (from GET /engines) this provider is listed under, to read whether it works. */
  engineIds: readonly string[]
}

/** The four AIs the service can judge with. */
export const PROVIDERS: readonly JudgingProvider[] = [
  { id: 'openrouter', label: 'OpenRouter', engineIds: ['openrouter'] },
  { id: 'claude_code', label: 'Claude (your subscription)', engineIds: ['claude_code', 'claude'] },
  { id: 'gemini', label: 'Google Gemini API', engineIds: ['gemini'] },
  { id: 'antigravity', label: 'Antigravity (your Google plan)', engineIds: ['antigravity'] },
]

/** How many AIs may be tried after the first choice. */
export const MAX_FALLBACK = 3

const KNOWN = new Set(PROVIDERS.map((provider) => provider.id))

/** The fallback order from its stored text: known names only, no repeats, at most MAX_FALLBACK. */
export function parseFallback(stored: unknown): string[] {
  const names = String(stored ?? '')
    .split(',')
    .map((name) => name.trim())
    .filter((name) => KNOWN.has(name))
  return names.filter((name, index) => names.indexOf(name) === index).slice(0, MAX_FALLBACK)
}

/** The stored text for a fallback order. */
export function joinFallback(order: readonly string[]): string {
  return order.join(',')
}

/** The engine row that tells whether a provider works, when the engine list has one. */
export function engineFor(provider: JudgingProvider, engines: readonly EngineRow[]): EngineRow | undefined {
  return engines.find((engine) => provider.engineIds.includes(engine.id))
}

/** The name to show for a provider: the engine list's own label when it has one. */
export function providerName(provider: JudgingProvider, engines: readonly EngineRow[]): string {
  return engineFor(provider, engines)?.label ?? provider.label
}
