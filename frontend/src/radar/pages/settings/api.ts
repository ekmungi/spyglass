// The Settings page's only door to the server: the assistant engines (/api/radar/engines) and the
// editable settings (/api/settings). API keys are sent once and never come back.
import { getPrivacyOutbound, request } from '../../api/client'
import { isMissing } from '../../api/errors'
import type { Engine, EngineUpdate, PrivacyOutbound } from '../../api/types'
import { requestJson } from '../sources/http'

/** An engine as the service describes it, including key and default details (never the key itself). */
export type EngineRow = Engine

/** What a PUT to an engine accepts. */
export type EngineChange = EngineUpdate & { label?: string; default_model?: string }

export type SettingsValues = Record<string, unknown>

/** Drop anything secret-looking from an engine reply, so a key can never end up on screen. */
export function withoutSecret(row: EngineRow): EngineRow {
  return Object.fromEntries(Object.entries(row).filter(([name]) => name !== 'api_key')) as EngineRow
}

/** Every engine with its availability, models and key state. */
export async function loadEngines(signal?: AbortSignal): Promise<EngineRow[]> {
  const raw = await request<unknown>('GET', '/engines', undefined, signal)
  const rows = Array.isArray(raw) ? raw : ((raw as { engines?: unknown } | null)?.engines ?? [])
  return (rows as EngineRow[]).map(withoutSecret)
}

/** Configure one engine. A key in `change` is stored in the operating system's key store and never returned. */
export async function configureEngine(id: string, change: EngineChange): Promise<EngineRow> {
  return withoutSecret(await request<EngineRow>('PUT', `/engines/${encodeURIComponent(id)}`, change))
}

/** Remove a custom server and its stored key. */
export const removeEngine = (id: string) => request<unknown>('DELETE', `/engines/${encodeURIComponent(id)}`)

/** The editable settings. */
export const loadSettings = (): Promise<SettingsValues> => requestJson<SettingsValues>('GET', '/api/settings')

/** Change some settings; resolves to the settings as stored. */
export const patchSettings = (change: SettingsValues): Promise<SettingsValues> => requestJson<SettingsValues>('PATCH', '/api/settings', change)

/** What Spyglass sends out and the four privacy switches; null when this copy of the service has no such overview yet. */
export async function loadPrivacy(signal?: AbortSignal): Promise<PrivacyOutbound | null> {
  try {
    return await getPrivacyOutbound(signal)
  } catch (cause) {
    if (isMissing(cause)) return null
    throw cause
  }
}

/** Keys of `sent` that the reply does not report back with the same value (the service may not support them). */
export function unconfirmedKeys(sent: SettingsValues, stored: SettingsValues | null): string[] {
  return Object.entries(sent)
    .filter(([name, value]) => !stored || !(name in stored) || String(stored[name] ?? '') !== String(value ?? ''))
    .map(([name]) => name)
}
