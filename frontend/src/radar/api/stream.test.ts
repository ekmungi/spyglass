// Tests for the assistant stream: SSE parsing across chunk boundaries, keep-alives, error
// events, abort, and HTTP failures.
import { afterEach, describe, expect, it } from 'vitest'
import { ApiError } from './errors'
import { createSseParser, parseEventData, readStream, streamMessage } from './stream'
import { setFetchForTesting } from './transport'
import type { StreamEvent } from './types'

afterEach(() => setFetchForTesting(null))

/** A byte stream that emits the given string chunks in order. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
}

describe('createSseParser', () => {
  it('reassembles events split across chunks, mid-line and mid-JSON', () => {
    const parser = createSseParser()
    const events: StreamEvent[] = []
    for (const chunk of ['da', 'ta: {"type":"del', 'ta","text":"Hel"}\n', '\ndata: {"type":"delta","text":"lo"}\n\nda', 'ta: {"type":"done","message_id":7}\n\n']) {
      events.push(...parser.push(chunk))
    }
    expect(events).toEqual([
      { type: 'delta', text: 'Hel' },
      { type: 'delta', text: 'lo' },
      { type: 'done', message_id: 7 },
    ])
  })

  it('ignores keep-alive comments and handles CRLF line endings', () => {
    const parser = createSseParser()
    const events = parser.push(': ping\r\n\r\ndata: {"type":"delta","text":"a"}\r\n\r\n: ping\n\n')
    expect(events).toEqual([{ type: 'delta', text: 'a' }])
  })

  it('emits a final event without a trailing blank line on flush', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"type":"done","message_id":3}')).toEqual([])
    expect(parser.flush()).toEqual([{ type: 'done', message_id: 3 }])
  })

  it('skips malformed and unknown payloads', () => {
    const parser = createSseParser()
    expect(parser.push('data: not json\n\ndata: {"type":"other"}\n\n')).toEqual([])
  })
})

describe('parseEventData', () => {
  it('gives error events a readable message even when empty', () => {
    expect(parseEventData('{"type":"error","message":"Engine timed out"}')).toEqual({ type: 'error', message: 'Engine timed out' })
    expect(parseEventData('{"type":"error"}')).toEqual({ type: 'error', message: 'The assistant stopped with an error.' })
  })
})

describe('readStream', () => {
  it('collects the text and message id of a finished answer', async () => {
    const seen: StreamEvent[] = []
    const result = await readStream(streamOf(['data: {"type":"delta","text":"One "}\n\n', 'data: {"type":"delta","text":"two"}\n\ndata: {"type":"done","message_id":12}\n\n']), (event) => seen.push(event))
    expect(result).toEqual({ outcome: 'done', text: 'One two', messageId: 12, error: null })
    expect(seen).toHaveLength(3)
  })

  it('reports an error event with the partial text', async () => {
    const result = await readStream(streamOf(['data: {"type":"delta","text":"Partial"}\n\n', 'data: {"type":"error","message":"Rate limited"}\n\n']), () => undefined)
    expect(result.outcome).toBe('error')
    expect(result.error).toBe('Rate limited')
    expect(result.text).toBe('Partial')
  })

  it('treats a stream that ends without done as cut off', async () => {
    const result = await readStream(streamOf(['data: {"type":"delta","text":"Half"}\n\n']), () => undefined)
    expect(result.outcome).toBe('error')
    expect(result.error).toMatch(/cut off/)
  })

  it('stops and reports aborted when the signal fires', async () => {
    const controller = new AbortController()
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(stream) {
        stream.enqueue(encoder.encode('data: {"type":"delta","text":"Start"}\n\n'))
        // never closes: only the abort can end this read
      },
    })
    const pending = readStream(body, (event) => {
      if (event.type === 'delta') controller.abort()
    }, controller.signal)
    const result = await pending
    expect(result.outcome).toBe('aborted')
    expect(result.text).toBe('Start')
  })
})

describe('streamMessage', () => {
  it('posts the body and streams the reply', async () => {
    let sent: RequestInit | undefined
    setFetchForTesting(async (_url, init) => {
      sent = init
      return new Response(streamOf(['data: {"type":"delta","text":"Hi"}\n\ndata: {"type":"done","message_id":1}\n\n']), { status: 200 })
    })
    const result = await streamMessage(4, { content: '', action: 'explain', selection: 'a passage' }, () => undefined)
    expect(result.outcome).toBe('done')
    expect(sent?.method).toBe('POST')
    expect(JSON.parse(String(sent?.body))).toEqual({ content: '', action: 'explain', selection: 'a passage' })
  })

  it('throws an ApiError with the server detail for a 4xx reply', async () => {
    setFetchForTesting(async () => new Response(JSON.stringify({ detail: 'No engine is configured.' }), { status: 409 }))
    await expect(streamMessage(4, { content: 'Hello' }, () => undefined)).rejects.toMatchObject({ status: 409, message: 'No engine is configured.' })
  })

  it('returns aborted instead of throwing when stopped before the reply arrives', async () => {
    setFetchForTesting(async () => {
      throw new DOMException('Aborted', 'AbortError')
    })
    const result = await streamMessage(4, { content: 'Hello' }, () => undefined)
    expect(result.outcome).toBe('aborted')
  })

  it('throws a network ApiError when the service is unreachable', async () => {
    setFetchForTesting(async () => {
      throw new TypeError('Failed to fetch')
    })
    const error = await streamMessage(4, { content: 'Hello' }, () => undefined).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).kind).toBe('network')
  })
})
