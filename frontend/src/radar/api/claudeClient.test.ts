// Tests for the client calls added for Claude Code, projects and the privacy overview: the exact
// paths, methods and bodies they send, and how a 404 (an endpoint not in this copy yet) reads.
import { afterEach, describe, expect, it } from 'vitest'
import { getPrivacyOutbound, getProjects, openInClaude, previewClaude, putProjects, queryString } from './client'
import { isMissing } from './errors'
import { loadProjects, saveProjects } from './projects'
import { setFetchForTesting } from './transport'

interface Seen {
  url: string
  method: string | undefined
  body: unknown
}

/** Serve one canned reply and record the request. */
function serve(reply: unknown, status = 200): Seen {
  const seen: Seen = { url: '', method: undefined, body: undefined }
  setFetchForTesting(async (url, init) => {
    seen.url = url
    seen.method = init?.method
    seen.body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    return new Response(reply === null ? null : JSON.stringify(reply), { status, headers: { 'Content-Type': 'application/json' } })
  })
  return seen
}

afterEach(() => setFetchForTesting(null))

describe('Open in Claude Code calls', () => {
  it('previews with POST /items/{id}/claude/preview and the choice as the body', async () => {
    const seen = serve({ text: 'T', vault: null, available: true, reason: null })
    const reply = await previewClaude(12, { intent: 'file', project: 'Imaging AI', as_kind: 'resource' })
    expect(seen).toEqual({ url: '/api/radar/items/12/claude/preview', method: 'POST', body: { intent: 'file', project: 'Imaging AI', as_kind: 'resource' } })
    expect(reply.text).toBe('T')
  })

  it('opens with POST /items/{id}/claude/open and the same kind of body', async () => {
    const seen = serve({ opened: true })
    expect(await openInClaude(12, { intent: 'custom', custom: 'Compare' })).toEqual({ opened: true })
    expect(seen).toEqual({ url: '/api/radar/items/12/claude/open', method: 'POST', body: { intent: 'custom', custom: 'Compare' } })
  })

  it('reads a readable detail from a refusal', async () => {
    serve({ detail: 'Claude Code is not installed.' }, 422)
    await expect(openInClaude(1, { intent: 'discuss' })).rejects.toThrow('Claude Code is not installed.')
  })
})

describe('projects calls', () => {
  it('reads GET /projects into a list', async () => {
    const seen = serve({ projects: [{ name: 'A', description: 'a', in_vault: true }] })
    expect(await getProjects()).toEqual([{ name: 'A', description: 'a', in_vault: true }])
    expect(seen).toMatchObject({ url: '/api/radar/projects', method: 'GET' })
  })

  it('saves with PUT /projects and {projects: [{name, description}]}', async () => {
    const seen = serve({ projects: [] })
    await putProjects({ projects: [{ name: 'A', description: 'a' }] })
    expect(seen).toEqual({ url: '/api/radar/projects', method: 'PUT', body: { projects: [{ name: 'A', description: 'a' }] } })
  })

  it('sends only the projects that have a line, trimmed, so the rest stay private', async () => {
    const seen = serve({ projects: [] })
    await saveProjects([
      { name: 'A', description: '  Real-time detection.  ', in_vault: true },
      { name: 'B', description: '   ', in_vault: true },
      { name: 'C', description: '', in_vault: false },
    ])
    expect(seen.body).toEqual({ projects: [{ name: 'A', description: 'Real-time detection.' }] })
  })

  it('reads a missing endpoint (404) as null instead of failing', async () => {
    serve({ detail: 'Not found' }, 404)
    expect(await loadProjects()).toBeNull()
  })

  it('still fails for any other error', async () => {
    serve({ detail: 'broken' }, 500)
    await expect(loadProjects()).rejects.toThrow()
  })
})

describe('privacy and the 404 test', () => {
  it('reads GET /privacy/outbound', async () => {
    const seen = serve({ model_provider: { name: 'OpenRouter', host: 'openrouter.ai' } })
    await getPrivacyOutbound()
    expect(seen).toMatchObject({ url: '/api/radar/privacy/outbound', method: 'GET' })
  })

  it('tells a 404 from other errors', async () => {
    serve({ detail: 'Not found' }, 404)
    const missing = await getPrivacyOutbound().catch((cause: unknown) => cause)
    expect(isMissing(missing)).toBe(true)
    serve({ detail: 'broken' }, 500)
    const broken = await getPrivacyOutbound().catch((cause: unknown) => cause)
    expect(isMissing(broken)).toBe(false)
    expect(isMissing(new Error('x'))).toBe(false)
  })

  it('sends the filed filter to the feed as filed=true', () => {
    expect(queryString({ filed: true, saved: undefined })).toBe('?filed=true')
  })
})
