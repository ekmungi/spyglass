// ApiError: every failed radar request becomes one typed error with a message a reader can act on.

export type ApiErrorKind = 'network' | 'http' | 'parse' | 'aborted'

export class ApiError extends Error {
  readonly status: number
  readonly kind: ApiErrorKind
  readonly path: string
  readonly detail: string | null

  /** status is the HTTP status (0 when the request never reached the server). */
  constructor(message: string, options: { status: number; kind: ApiErrorKind; path: string; detail?: string | null }) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.kind = options.kind
    this.path = options.path
    this.detail = options.detail ?? null
  }
}

/** Replace a validation message the reader cannot act on with a plain sentence. */
export function tidyDetail(text: string): string {
  if (/at most 2048 characters/i.test(text)) return 'That address is too long.'
  return text
}

/** Pull FastAPI's `detail` (a string or a list of validation errors) out of an error body. */
export function extractDetail(body: unknown): string | null {
  if (!body || typeof body !== 'object') return typeof body === 'string' && body.trim() ? body.trim() : null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return tidyDetail(detail)
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry && typeof entry === 'object' ? (entry as { msg?: unknown }).msg : null))
      .filter((msg): msg is string => typeof msg === 'string')
    return messages.length ? messages.map(tidyDetail).join('; ') : null
  }
  const message = (body as { message?: unknown }).message
  return typeof message === 'string' ? message : null
}

/** The plain-language message for an HTTP status, used when the server sends no usable detail. */
export function messageForStatus(status: number): string {
  if (status === 400 || status === 422) return 'The request was not accepted. Check what you entered and try again.'
  if (status === 401 || status === 403) return 'Spyglass refused this request.'
  if (status === 404) return 'That item or page no longer exists.'
  if (status === 409) return 'This is already in progress. Try again in a moment.'
  if (status === 429) return 'Too many requests at once. Wait a moment and try again.'
  if (status === 502 || status === 503 || status === 504) return 'Spyglass or a service it relies on is not responding. Try again shortly.'
  if (status >= 500) return 'Spyglass hit an error while doing this. Try again; if it repeats, check the service log.'
  return `The request failed (status ${status}).`
}

/** Build the ApiError for a non-OK response; a 4xx detail is shown to the reader, a 5xx detail is kept aside. */
export function httpError(status: number, body: unknown, path: string): ApiError {
  const detail = extractDetail(body)
  const useDetail = detail !== null && status >= 400 && status < 500 && status !== 401 && status !== 403
  return new ApiError(useDetail ? detail : messageForStatus(status), { status, kind: 'http', path, detail })
}

/** Build the ApiError for a request that never got a response (service down, offline) or was aborted. */
export function transportError(cause: unknown, path: string): ApiError {
  if (cause instanceof DOMException && cause.name === 'AbortError') {
    return new ApiError('The request was cancelled.', { status: 0, kind: 'aborted', path })
  }
  return new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', {
    status: 0,
    kind: 'network',
    path,
    detail: cause instanceof Error ? cause.message : null,
  })
}

/**
 * True when the service answered 404: for an endpoint added in a newer copy of the service this
 * means "not available in this copy yet", and the interface says so calmly instead of failing.
 */
export function isMissing(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/** The sentence shown where a feature's endpoint is not in this copy of the service yet. */
export const NOT_AVAILABLE_YET = 'This is not available in this copy of Spyglass yet.'

/** Human message for any thrown value (ApiError or not), for inline error text. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return 'Something went wrong.'
}
