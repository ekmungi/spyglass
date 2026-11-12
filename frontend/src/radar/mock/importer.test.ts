// Sample mode answers the import endpoints the way the service does.
import { beforeEach, describe, expect, it } from 'vitest'
import { mockFetch, resetMockState } from './index'

const key = async () => (await (await mockFetch('/api/radar/import/button-key')).json()).key as string
const post = (path: string, body: unknown) =>
  mockFetch(`/api/radar${path}`, { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } })

beforeEach(() => resetMockState())

describe('sample import routes', () => {
  it('stages a page, previews it as text and adds it once', async () => {
    const staged = await post('/import/stage', { url: 'https://news.example.com/a', title: 'A', html: '<nav>menu</nav><p>Hello <b>reader</b></p>', sender: 'https://news.example.com', key: await key() })
    const { token } = await staged.json()
    expect(token).toMatch(/^[0-9a-f]{32}$/)
    const preview = await (await mockFetch(`/api/radar/import/staged/${token}`)).json()
    expect(preview).toMatchObject({ host: 'news.example.com', excerpt: 'Hello reader', sender: 'news.example.com', sender_matches: true, replaces_existing: false })
    const added = await (await post(`/import/staged/${token}/accept`, {})).json()
    expect(added.state).toMatchObject({ from_user: true, captured_via: 'browser' })
    expect((await post(`/import/staged/${token}/accept`, {})).status).toBe(404)
  })

  it('adds pasted text and a file, and refuses a bad address', async () => {
    const text = await (await post('/import/text', { url: 'https://news.example.com/b', text: 'Headline\n\nBody' })).json()
    expect(text).toMatchObject({ title: 'Headline', state: { captured_via: 'paste' } })
    const form = new FormData()
    form.set('url', 'https://news.example.com/c')
    form.set('file', new File(['%PDF-1.4'], 'paper.pdf'))
    const file = await (await mockFetch('/api/radar/import/file', { method: 'POST', body: form })).json()
    expect(file).toMatchObject({ title: 'paper', state: { captured_via: 'file' } })
    expect((await post('/import/stage', { url: 'http://localhost/x', html: '<p>x</p>', key: await key() })).status).toBe(400)
  })

  it('refuses a page without the button key, and a rotated key stops older buttons', async () => {
    const page = { url: 'https://news.example.com/k', title: 'K', html: '<p>Hello reader</p>', sender: 'https://news.example.com' }
    expect((await post('/import/stage', page)).status).toBe(403)
    const old = await key()
    expect((await post('/import/stage', { ...page, key: old })).status).toBe(200)
    const fresh = (await (await post('/import/button-key/rotate', {})).json()).key as string
    expect(fresh).not.toBe(old)
    expect((await post('/import/stage', { ...page, key: old })).status).toBe(403)
    expect((await post('/import/stage', { ...page, key: fresh })).status).toBe(200)
  })
})
