// Assistant stream: POSTs a message and reads the server-sent `data: {json}` lines from the
// response body (EventSource cannot POST). Aborting the signal stops the read.
import { ApiError, httpError, transportError } from './errors'
import { apiFetch } from './transport'
import type { RetrievedItem, SendMessageBody, StreamEvent } from './types'

/** The items a feed answer could cite, from a `done` event; anything malformed is dropped, none at all gives undefined. */
function parseRetrieved(value: unknown): RetrievedItem[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.flatMap((entry): RetrievedItem[] => {
    const row = entry as { id?: unknown; headline?: unknown } | null
    return row && Number.isInteger(row.id) && typeof row.headline === 'string' ? [{ id: row.id as number, headline: row.headline }] : []
  })
}

/** Turn one `data:` payload into a StreamEvent; unknown or malformed payloads return null. */
export function parseEventData(data: string): StreamEvent | null {
  let value: unknown
  try {
    value = JSON.parse(data)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object') return null
  const event = value as Record<string, unknown>
  if (event.type === 'delta' && typeof event.text === 'string') return { type: 'delta', text: event.text }
  if (event.type === 'done') {
    const retrieved = parseRetrieved(event.retrieved)
    return { type: 'done', message_id: Number(event.message_id ?? 0), ...(retrieved ? { retrieved } : {}) }
  }
  if (event.type === 'error') {
    return { type: 'error', message: typeof event.message === 'string' && event.message ? event.message : 'The assistant stopped with an error.' }
  }
  return null
}

/**
 * An incremental SSE parser. Feed it text chunks in arrival order; it returns the events that
 * completed in that chunk and keeps any partial line for the next call. Events are separated by a
 * blank line; several `data:` lines in one event are joined with a newline, as the SSE spec says.
 */
export function createSseParser(): { push: (chunk: string) => StreamEvent[]; flush: () => StreamEvent[] } {
  let buffer = ''
  let dataLines: string[] = []

  const finishEvent = (out: StreamEvent[]) => {
    if (dataLines.length === 0) return
    const parsed = parseEventData(dataLines.join('\n'))
    dataLines = []
    if (parsed) out.push(parsed)
  }

  const handleLine = (line: string, out: StreamEvent[]) => {
    if (line === '') {
      finishEvent(out)
      return
    }
    if (line.startsWith(':')) return // comment / keep-alive
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    // Other fields (event:, id:, retry:) are not used by this contract.
  }

  return {
    push(chunk: string) {
      const out: StreamEvent[] = []
      buffer += chunk
      const lines = buffer.split(/\r\n|\r|\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) handleLine(line, out)
      return out
    },
    flush() {
      const out: StreamEvent[] = []
      if (buffer) {
        handleLine(buffer, out)
        buffer = ''
      }
      finishEvent(out)
      return out
    },
  }
}

export interface StreamResult {
  /** 'done' when the server finished, 'error' when it sent an error event, 'aborted' when stopped. */
  outcome: 'done' | 'error' | 'aborted'
  text: string
  messageId: number | null
  error: string | null
}

/**
 * Send a message to a thread and stream the answer. `onEvent` receives each event as it arrives.
 * Resolves with the outcome; rejects only with an ApiError for a failed request (network or HTTP).
 */
export async function streamMessage(
  threadId: number,
  body: SendMessageBody,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<StreamResult> {
  const path = `/threads/${threadId}/messages`
  let response: Response
  try {
    response = await apiFetch(path, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch (cause) {
    const error = transportError(cause, path)
    if (error.kind === 'aborted') return { outcome: 'aborted', text: '', messageId: null, error: null }
    throw error
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let parsed: unknown = text
    try {
      parsed = text ? JSON.parse(text) : null
    } catch {
      /* keep the raw text as the detail */
    }
    throw httpError(response.status, parsed, path)
  }
  if (!response.body) {
    throw new ApiError('The assistant reply arrived without a body.', { status: response.status, kind: 'parse', path })
  }
  return readStream(response.body, onEvent, signal)
}

/** Read a byte stream of SSE lines to completion, aborting cleanly when the signal fires. */
export async function readStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<StreamResult> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const parser = createSseParser()
  // One mutable accumulator, local to this read, filled as events arrive.
  const acc: { text: string; messageId: number | null; error: string | null; outcome: StreamResult['outcome'] | null } = {
    text: '',
    messageId: null,
    error: null,
    outcome: null,
  }
  const aborted = (): StreamResult => ({ outcome: 'aborted', text: acc.text, messageId: acc.messageId, error: acc.error })

  const onAbort = () => {
    reader.cancel().catch(() => undefined)
  }
  signal?.addEventListener('abort', onAbort)

  const handle = (events: StreamEvent[]) => {
    for (const event of events) {
      if (acc.outcome) return // nothing after done/error counts
      if (event.type === 'delta') acc.text += event.text
      if (event.type === 'done') {
        acc.messageId = event.message_id || null
        acc.outcome = 'done'
      }
      if (event.type === 'error') {
        acc.error = event.message
        acc.outcome = 'error'
      }
      onEvent(event)
    }
  }

  try {
    while (!acc.outcome) {
      if (signal?.aborted) return aborted()
      const { done, value } = await reader.read()
      if (done) break
      handle(parser.push(decoder.decode(value, { stream: true })))
    }
    if (!acc.outcome) {
      handle(parser.push(decoder.decode()))
      handle(parser.flush())
    }
  } catch (cause) {
    if (signal?.aborted) return aborted()
    return { outcome: 'error', text: acc.text, messageId: acc.messageId, error: cause instanceof Error ? cause.message : 'The connection dropped.' }
  } finally {
    signal?.removeEventListener('abort', onAbort)
  }
  if (signal?.aborted && acc.outcome !== 'done') return aborted()
  if (!acc.outcome) {
    // The stream ended without a done or error event: treat it as an interrupted answer.
    return { outcome: 'error', text: acc.text, messageId: acc.messageId, error: 'The answer was cut off before it finished.' }
  }
  return { outcome: acc.outcome, text: acc.text, messageId: acc.messageId, error: acc.error }
}
