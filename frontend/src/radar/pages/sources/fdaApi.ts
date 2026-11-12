// The FDA section's door to the server: the three FDA settings live in the general settings
// endpoint, so reading and saving them goes through /api/settings.
import { requestJson } from './http'

export interface FdaSettings {
  /** Whether the daily FDA lookup runs. */
  enabled: boolean
  /** Comma-separated product codes to watch beyond the watch list, e.g. "QAS, NAY". */
  productCodes: string
  /** Comma-separated device words to watch beyond the watch list. */
  keywords: string
}

type Raw = Record<string, unknown>

const text = (value: unknown): string => (typeof value === 'string' ? value : '')

/** The FDA settings out of a settings reply (missing fields read as the defaults: on, empty lists). */
export function toFdaSettings(raw: unknown): FdaSettings {
  const body = (raw && typeof raw === 'object' ? raw : {}) as Raw
  return {
    enabled: body.radar_fda_enabled !== false,
    productCodes: text(body.radar_fda_product_codes),
    keywords: text(body.radar_fda_keywords),
  }
}

/** Read the current FDA settings. */
export async function loadFdaSettings(): Promise<FdaSettings> {
  return toFdaSettings(await requestJson<Raw>('GET', '/api/settings'))
}

/** Save some or all of the FDA settings and return what the server now holds. */
export async function saveFdaSettings(change: Partial<FdaSettings>): Promise<FdaSettings> {
  const body: Raw = {}
  if (change.enabled !== undefined) body.radar_fda_enabled = change.enabled
  if (change.productCodes !== undefined) body.radar_fda_product_codes = change.productCodes
  if (change.keywords !== undefined) body.radar_fda_keywords = change.keywords
  return toFdaSettings(await requestJson<Raw>('PATCH', '/api/settings', body))
}

/** A plain sentence when a list holds characters the server would refuse, else null. */
export function listProblem(settings: Pick<FdaSettings, 'productCodes' | 'keywords'>): string | null {
  if (!/^[A-Za-z0-9, ]*$/.test(settings.productCodes)) {
    return 'Product codes can only hold letters, digits, spaces and commas, for example "QAS, NAY".'
  }
  if (!/^[A-Za-z0-9 ,.'/&()-]*$/.test(settings.keywords)) {
    return 'Keywords can only hold letters, digits, spaces and the marks . , \' / & ( ) -'
  }
  return null
}
