// JSON requests to the older Spyglass endpoints (/api/feeds, /api/settings) that live outside
// /api/radar. Failures become ApiError with a plain sentence a reader can act on.
import { ApiError, extractDetail, messageForStatus, transportError } from '../../api/errors'
import { isMockMode } from '../../api/transport'
import { legacyMock } from './legacyMock'

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

/** Sample mode: answer from the local sample data after a short pause, so loading states show. */
async function sampleResponse(method: Method, path: string, body: unknown): Promise<Response> {
  await new Promise((resolve) => setTimeout(resolve, 200))
  const reply = legacyMock(method, path, (body ?? {}) as Record<string, unknown>)
  if (!reply) return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
  return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/json' } })
}

/** The feed endpoints explain failures as {detail: {kind, url, reason}}; pull the sentence out. */
function nestedReason(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null
  const reason = (detail as { reason?: unknown }).reason
  return typeof reason === 'string' && reason.trim() ? reason.trim() : null
}

/** Send one JSON request to an absolute same-origin path and parse the JSON reply (null when empty). */
export async function requestJson<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    headers: body === undefined ? { Accept: 'application/json' } : { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
  let response: Response
  try {
    response = isMockMode() ? await sampleResponse(method, path, body) : await fetch(path, init)
  } catch (cause) {
    throw transportError(cause, path)
  }
  const text = await response.text().catch(() => '')
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      if (response.ok) {
        throw new ApiError('Spyglass sent a reply this page could not read.', { status: response.status, kind: 'parse', path })
      }
    }
  }
  if (!response.ok) {
    const reason = nestedReason(parsed)
    const detail = extractDetail(parsed)
    const showDetail = response.status >= 400 && response.status < 500 && response.status !== 401 && response.status !== 403
    const message = reason ?? (showDetail && detail ? detail : messageForStatus(response.status))
    throw new ApiError(message, { status: response.status, kind: 'http', path, detail: reason ?? detail })
  }
  return parsed as T
}
