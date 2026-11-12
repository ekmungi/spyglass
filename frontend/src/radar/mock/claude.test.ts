// Tests for the sample-mode answers to Claude Code, projects and privacy: the shapes the real
// service is expected to send, so sample mode and the interface agree with it.
import { beforeEach, describe, expect, it } from 'vitest'
import { mockFetch, resetMockState } from '.'

beforeEach(() => resetMockState())

/** Call the sample service the way the client does. */
async function call(method: string, path: string, body?: unknown) {
  const response = await mockFetch(`/api/radar${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  return { status: response.status, json: (await response.json().catch(() => null)) as Record<string, unknown> | null }
}

describe('sample Claude Code answers', () => {
  it('previews text, vault, availability and reason', async () => {
    const { status, json } = await call('POST', '/items/101/claude/preview', { intent: 'file', project: 'Imaging AI', as_kind: 'resource' })
    expect(status).toBe(200)
    expect(json).toMatchObject({ vault: expect.any(String), available: true, reason: null })
    expect(String(json?.text)).toContain('Imaging AI')
    expect(String(json?.text)).toContain('resource')
  })

  it('writes a different text for discuss and for the reader\'s own request', async () => {
    const discuss = await call('POST', '/items/101/claude/preview', { intent: 'discuss' })
    const custom = await call('POST', '/items/101/claude/preview', { intent: 'custom', custom: 'Compare it with my notes' })
    expect(String(discuss.json?.text)).toMatch(/discuss/i)
    expect(String(custom.json?.text)).toContain('Compare it with my notes')
  })

  it('names a project the reader wrote in their note', async () => {
    await call('POST', '/capture', { url: 'https://example.org/x', note: 'Useful for the Imaging AI work' })
    const feed = await call('GET', '/feed?from_user=true')
    const created = (feed.json?.items as { id: number; state: { note?: string } }[]).find((item) => item.state.note?.includes('Imaging AI'))
    const { json } = await call('POST', `/items/${created?.id}/claude/preview`, { intent: 'file' })
    expect(json?.project_hint).toEqual({ name: 'Imaging AI', source: 'note' })
  })

  it('opens, and answers 404 for an item that does not exist', async () => {
    expect((await call('POST', '/items/101/claude/open', { intent: 'discuss' })).json).toEqual({ opened: true })
    expect((await call('POST', '/items/99999/claude/preview', { intent: 'discuss' })).status).toBe(404)
  })

  it('starts one sent-in item as already filed, and filters on it', async () => {
    const filed = await call('GET', '/feed?filed=true')
    const items = filed.json?.items as { filed: { path: string; project: string | null; at: string } }[]
    expect(items.length).toBe(1)
    expect(items[0].filed).toMatchObject({ path: expect.any(String), project: 'Regulation notes', at: expect.any(String) })
  })
})

describe('sample projects', () => {
  it('lists projects with a line and whether they are in the vault', async () => {
    const { json } = await call('GET', '/projects')
    const projects = json?.projects as { name: string; description: string; in_vault: boolean }[]
    expect(projects.length).toBeGreaterThan(2)
    expect(projects.some((project) => !project.in_vault)).toBe(true)
    expect(Object.keys(projects[0]).sort()).toEqual(['description', 'in_vault', 'name'])
  })

  it('keeps the lines it is sent and blanks the rest', async () => {
    const { json } = await call('PUT', '/projects', { projects: [{ name: 'Agent harness', description: 'Tools for coding agents.' }] })
    const projects = json?.projects as { name: string; description: string }[]
    expect(projects.find((project) => project.name === 'Agent harness')?.description).toBe('Tools for coding agents.')
    expect(projects.find((project) => project.name === 'Imaging AI')?.description).toBe('')
  })
})

describe('sample privacy overview', () => {
  it('has the documented shape', async () => {
    const { json } = await call('GET', '/privacy/outbound')
    expect(json).toMatchObject({
      model_provider: { name: expect.any(String), host: expect.any(String) },
      profile_block: expect.any(String),
      example_titles: { liked: expect.any(Array), disliked: expect.any(Array) },
      destinations: expect.any(Array),
      switches: { privacy_send_examples: true, privacy_proxy_images: true, jina_enabled: false, privacy_allow_bot_checks: true },
    })
    const destination = (json?.destinations as Record<string, unknown>[])[0]
    expect(Object.keys(destination).sort()).toEqual(['carries_secret', 'enabled', 'host', 'name', 'purpose', 'what_is_sent'])
  })
})
