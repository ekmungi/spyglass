// Sample-mode answers for the older endpoints (/api/feeds, /api/settings) that the shared sample
// data does not cover, so Sources and Settings can be clicked through with ?mock=1 and no backend.

type Json = Record<string, unknown>

interface SampleFeed extends Json {
  id: number
  feed_url: string
  name: string
  enabled: boolean
}

let feeds: SampleFeed[] = []
let nextFeedId = 100
let settings: Json = {
  vault_path: 'C:/Notes/Vault',
  radar_brief_time: '06:30',
  radar_timezone: '',
  radar_collect_hours: 2,
  assist_default_engine: '',
  assist_default_model: '',
  radar_llm_provider: 'openrouter',
  radar_llm_fallback: '',
  privacy_send_examples: true,
  privacy_proxy_images: true,
  jina_enabled: false,
  privacy_allow_bot_checks: true,
  radar_fda_enabled: true,
  radar_fda_product_codes: '',
  radar_fda_keywords: '',
}

/** The sample settings as they stand now (the sample privacy overview reads its switches from here). */
export function sampleSettings(): Json {
  return settings
}

/** A response-like pair the caller turns into JSON or an error. */
export interface SampleReply {
  status: number
  body: unknown
}

/** Answer one request in sample mode; null when the path is not one of the older endpoints. */
export function legacyMock(method: string, path: string, body: Json): SampleReply | null {
  if (path === '/api/settings' && method === 'GET') return { status: 200, body: settings }
  if (path === '/api/settings' && method === 'PATCH') {
    settings = { ...settings, ...body }
    return { status: 200, body: settings }
  }
  if (path === '/api/feeds/discover' && method === 'POST') {
    const url = String(body.url ?? '')
    return {
      status: 200,
      body: { candidates: [{ feed_url: `${url.replace(/\/$/, '')}/feed`, name: 'Sample feed', kind: 'rss', already_subscribed: false }], reason: null },
    }
  }
  if (path === '/api/feeds' && method === 'POST') {
    const url = String(body.url ?? '')
    if (!/\/(feed|rss)/i.test(url)) {
      return { status: 422, body: { detail: { kind: 'not_a_feed', url, reason: 'That address is a web page, not a feed.' } } }
    }
    const feed: SampleFeed = { id: nextFeedId++, feed_url: url, name: String(body.name ?? 'New feed'), enabled: true, kind: 'rss', last_fetch_status: null, last_fetch_at: null, last_error: null, item_count: 0, added_via: 'manual' }
    feeds = [...feeds, feed]
    return { status: 200, body: feed }
  }
  const match = /^\/api\/feeds\/(\d+)$/.exec(path)
  if (match && method === 'PATCH') {
    return { status: 200, body: { id: Number(match[1]), ...body } }
  }
  if (match && method === 'DELETE') return { status: 200, body: { deleted: true, cards_removed: 0 } }
  return null
}
