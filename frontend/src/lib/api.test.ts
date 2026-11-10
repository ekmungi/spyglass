// Tests for the API wrappers: query building and failure behavior.
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'

afterEach(() => vi.unstubAllGlobals())

describe('api', () => {
  it('throws a readable error when the service answers with a failure code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))
    await expect(api.getRuns()).rejects.toThrow('GET /api/runs failed: 500')
  })

  it('passes filters as query parameters', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.getCards({ source: 'rss' })
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards?source=rss')
  })

  it('labels failures with the method that failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('no', { status: 422 })))
    await expect(api.patchCard(1, { note: 'x' })).rejects.toThrow('PATCH')
  })

  it('fetches one card in full for the reader', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"id":7,"summary":"Full summary."}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.getCard(7)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/7')
  })

  it('reads a card full text from the content endpoint', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"status":"ok","markdown":"x"}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.getFulltext(3)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/3/fulltext')
  })

  it('queues an on-demand fetch with POST and returns the job', async () => {
    const stub = vi.fn<typeof fetch>(
      async () =>
        new Response('{"job_id":5,"card_id":3,"status":"queued","error":null}', { status: 202 }),
    )
    vi.stubGlobal('fetch', stub)
    const job = await api.fetchFulltext(3)
    expect(stub.mock.calls[0][1]?.method).toBe('POST')
    expect(job).toEqual({ job_id: 5, card_id: 3, status: 'queued', error: null })
  })

  it('unwraps the active fetch-job card ids', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"card_ids":[4,9]}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await expect(api.getActiveFetchJobs()).resolves.toEqual([4, 9])
    expect(String(stub.mock.calls[0][0])).toBe('/api/fetch-jobs/active')
  })

  it('treats a response without card_ids as nothing in flight rather than crashing', async () => {
    // A cosmetic marker must never be able to take the dashboard down on an assumed shape —
    // the failure mode of an unchecked cast, avoided here by validating at the boundary.
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => new Response('{}', { status: 200 })))
    await expect(api.getActiveFetchJobs()).resolves.toEqual([])
  })

  it('hands back the linked-session prompt when Claude desktop cannot be opened', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"prompt":"call link_session"}', { status: 502 })),
    )
    const error = await api.openLinkedSession([3]).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(api.ClaudeUnavailableError)
    expect((error as api.ClaudeUnavailableError).prompt).toBe('call link_session')
  })

  it('opens a job without naming the ticked cards', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('{"opened":true}', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.openClaude('Process my inbox.', undefined, false)
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body)).include_selection).toBe(false)
  })

  it('sends the open item only when it is given', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.postSelection([1])
    await api.postSelection([1], null)
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({ card_ids: [1] })
    expect(JSON.parse(String(stub.mock.calls[1][1]?.body))).toEqual({ card_ids: [1], open_card_id: null })
  })

  it('encodes the search query', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.search('agent memory')
    expect(String(stub.mock.calls[0][0])).toBe('/api/search?q=agent+memory')
  })

  it('caps scored neighbours with k when given', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.getSimilar(4, 20)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/4/similar?k=20')
  })

  it('omits k from the similar query when not given', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.getSimilar(4)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/4/similar')
  })

  it('addPage posts the url and turns 400 into an honest message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('bad', { status: 400 })))
    await expect(api.addPage('not-a-url')).rejects.toThrow(/valid page URL/i)
  })

  it('renames a category through its endpoint', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"name":"Miscellaneous"}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.renameCategory('Misc', 'Miscellaneous')
    expect(String(stub.mock.calls[0][0])).toBe('/api/categories/Misc')
    expect(stub.mock.calls[0][1]?.method).toBe('PATCH')
  })

  it('lists and creates categories', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"name":"Robotics"}', { status: 201 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.createCategory('Robotics')
    expect(String(stub.mock.calls[0][0])).toBe('/api/categories')
    expect(stub.mock.calls[0][1]?.method).toBe('POST')
  })

  it('opens a Claude desktop session through open-claude', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"opened":true}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await expect(api.openClaude('run the relevance pass')).resolves.toEqual({ opened: true })
    expect(String(stub.mock.calls[0][0])).toBe('/api/open-claude')
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toMatchObject({
      prompt: 'run the relevance pass',
    })
  })

  it('hands back the prompt when the Claude desktop app cannot be opened', async () => {
    const stub = vi.fn<typeof fetch>(
      async () =>
        new Response('{"error":"claude_desktop_unavailable","prompt":"full prompt"}', {
          status: 502,
        }),
    )
    vi.stubGlobal('fetch', stub)
    const error = await api.openClaude('short').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(api.ClaudeUnavailableError)
    expect((error as api.ClaudeUnavailableError).prompt).toBe('full prompt')
  })

  it('reads and patches the service settings', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"relevance_threshold":"low"}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.getSettings()
    expect(String(stub.mock.calls[0][0])).toBe('/api/settings')
    await api.patchSettings({ relevance_threshold: 'low' })
    expect(stub.mock.calls[1][1]?.method).toBe('PATCH')
  })

  it('patches relevance and category through their endpoints', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"relevance":"high","relevance_override":true}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.setCardRelevance(4, 'high')
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/4/relevance')
    await api.setCardCategory(4, 'Robotics')
    expect(String(stub.mock.calls[1][0])).toBe('/api/cards/4/category')
    expect(stub.mock.calls[1][1]?.method).toBe('PATCH')
  })

  it('setCardRelevance(id, null) PATCHes with body {"relevance":null}', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"relevance":null,"relevance_override":false}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    await api.setCardRelevance(4, null)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/4/relevance')
    expect(stub.mock.calls[0][1]?.method).toBe('PATCH')
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({ relevance: null })
  })

  it('deletes a card via DELETE to its card endpoint', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"deleted":5}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    const result = await api.deleteCard(5)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/5')
    expect(stub.mock.calls[0][1]?.method).toBe('DELETE')
    expect(result).toEqual({ deleted: 5 })
  })

  it('opens a card in the system browser via POST to its open-external endpoint', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"opened":true,"url":"https://example.com"}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    const result = await api.openExternal(7)
    expect(String(stub.mock.calls[0][0])).toBe('/api/cards/7/open-external')
    expect(stub.mock.calls[0][1]?.method).toBe('POST')
    expect(result).toEqual({ opened: true, url: 'https://example.com' })
  })

  // --- Daily Brief API ---

  it('lists briefs from the briefs endpoint', async () => {
    const stub = vi.fn<typeof fetch>(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', stub)
    await api.getBriefs()
    expect(String(stub.mock.calls[0][0])).toBe('/api/briefs')
  })

  it('reads a single brief with its markdown', async () => {
    const stub = vi.fn<typeof fetch>(
      async () => new Response('{"id":3,"markdown":"# Brief"}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    const brief = await api.getBrief(3)
    expect(String(stub.mock.calls[0][0])).toBe('/api/briefs/3')
    expect(brief.markdown).toBe('# Brief')
  })

  it('generates briefs with POST and returns the composed list, status, and held count', async () => {
    const stub = vi.fn<typeof fetch>(
      async () =>
        new Response('{"composed":[{"id":4}],"status":"composed","held":0}', { status: 200 }),
    )
    vi.stubGlobal('fetch', stub)
    const result = await api.generateBrief()
    expect(String(stub.mock.calls[0][0])).toBe('/api/briefs/generate')
    expect(stub.mock.calls[0][1]?.method).toBe('POST')
    expect(result).toEqual({ composed: [{ id: 4 }], status: 'composed', held: 0 })
  })

  it('resolves an empty composed result when nothing is eligible to brief', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"composed":[],"status":"empty","held":0}', { status: 200 })),
    )
    await expect(api.generateBrief()).resolves.toEqual({ composed: [], status: 'empty', held: 0 })
  })

  it('throws BriefUnavailableError on 503 llm_unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('{"detail":{"status":"llm_unavailable"}}', { status: 503 }),
      ),
    )
    await expect(api.generateBrief()).rejects.toBeInstanceOf(api.BriefUnavailableError)
  })

  it('labels other brief-generation failures with the method and status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('boom', { status: 500 })))
    await expect(api.generateBrief()).rejects.toThrow('POST /api/briefs/generate failed: 500')
  })

})
