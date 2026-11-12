// Tests for the "Send to Spyglass" browser extension: its pure logic (browser-extension/lib.js,
// which the extension and these tests both import) and a check of its manifest and files.
import { describe, expect, it, vi } from 'vitest'
import {
  LIMITS,
  buildPayload,
  callSpyglass,
  checkSpyglass,
  chooseHtml,
  classifyPage,
  clipToBytes,
  describeOutcome,
  itemUrl,
  normalizeAddress,
  normalizeKey,
  sendToSpyglass,
  siteOf,
} from '../../../../browser-extension/lib.js'
import extensionManifest from '../../../../browser-extension/manifest.json'
import appManifest from '../../../../manifest.json'

const KEY = '0123456789abcdef0123456789abcdef'
const ADDRESS = 'http://localhost:7777'

/** A fake `fetch` that answers once with the given status and JSON body. */
function answering(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

describe('normalizeAddress', () => {
  it.each([
    ['http://localhost:7777', 'http://localhost:7777'],
    [' http://LOCALHOST:7778/ ', 'http://localhost:7778'],
    ['http://127.0.0.1:7777', 'http://127.0.0.1:7777'],
    ['http://localhost:80', 'http://localhost:80'],
  ])('accepts %s', (input, expected) => {
    expect(normalizeAddress(input)).toEqual({ ok: true, address: expected })
  })

  it.each([
    'https://localhost:7777',
    'http://localhost',
    'http://localhost:0',
    'http://localhost:70000',
    'http://example.com:7777',
    'http://localhost:7777.evil.example',
    'http://localhost:7777' + '@evil.example',
    'http://user:pw@localhost:7777',
    'http://localhost:7777/api',
    'http://localhost:7777?x=1',
    'http://192.168.1.4:7777',
    'localhost:7777',
    '',
    undefined,
  ])('refuses %s', (input) => {
    const result = normalizeAddress(input)
    expect(result.ok).toBe(false)
  })
})

describe('normalizeKey', () => {
  it('accepts the 32 letters and digits from Spyglass, ignoring spaces and capitals', () => {
    expect(normalizeKey(`  ${KEY.toUpperCase()}\n`)).toEqual({ ok: true, key: KEY })
  })

  it.each(['', 'short', KEY + '0', 'g'.repeat(32), undefined])('refuses %s', (input) => {
    expect(normalizeKey(input).ok).toBe(false)
  })
})

describe('page checks', () => {
  it('classifies addresses the extension can and cannot read', () => {
    expect(classifyPage('https://news.example.com/a')).toBe('ok')
    expect(classifyPage('http://news.example.com/a?x=1')).toBe('ok')
    expect(classifyPage('chrome://extensions')).toBe('internal')
    expect(classifyPage('vivaldi://settings')).toBe('internal')
    expect(classifyPage('about:blank')).toBe('internal')
    expect(classifyPage('file:///C:/x.html')).toBe('internal')
    expect(classifyPage(undefined)).toBe('internal')
    expect(classifyPage('https://example.com/paper.PDF')).toBe('pdf')
  })

  it('names the site without www', () => {
    expect(siteOf('https://www.news.example.com/a')).toBe('news.example.com')
    expect(siteOf('nonsense')).toBe('')
  })

  it('builds the address that opens an item', () => {
    expect(itemUrl(ADDRESS, 42)).toBe('http://localhost:7777/#/item/42')
  })
})

describe('size rules', () => {
  it('sends the whole page when it is at most 6 MB', () => {
    expect(chooseHtml({ full: '<p>small</p>', article: '<article>x</article>' })).toBe('<p>small</p>')
    const exact = 'a'.repeat(LIMITS.htmlBytes)
    expect(chooseHtml({ full: exact })).toBe(exact)
  })

  it('sends the article when the page is over 6 MB, else the main part', () => {
    const huge = 'a'.repeat(LIMITS.htmlBytes + 1)
    expect(chooseHtml({ full: huge, article: '<article>a</article>', main: '<main>m</main>' })).toBe('<article>a</article>')
    expect(chooseHtml({ full: huge, article: null, main: '<main>m</main>' })).toBe('<main>m</main>')
  })

  it('cuts to the first 2,000,000 characters when a big page has no usable article or main part', () => {
    const huge = 'a'.repeat(LIMITS.htmlBytes + 1)
    expect(chooseHtml({ full: huge, article: null, main: null })).toHaveLength(LIMITS.fallbackChars)
    const bigArticle = 'b'.repeat(LIMITS.htmlBytes + 5)
    expect(chooseHtml({ full: huge, article: bigArticle, main: null })).toHaveLength(LIMITS.fallbackChars)
  })

  it('counts bytes, not characters, when clipping text', () => {
    const clipped = clipToBytes('é'.repeat(10), 7)
    expect(clipped).toBe('ééé')
    expect(clipToBytes('short', 100)).toBe('short')
    expect(clipToBytes('a😀b', 4)).toBe('a')
  })
})

describe('buildPayload', () => {
  const page = { href: 'https://news.example.com/a', title: '  A title  ', full: '<html><body><p>Hello</p></body></html>' }

  it('builds a page payload with only the address, title, page, kind and note', () => {
    const built = buildPayload({ ...page, selectionText: 'ignored' }, 'page', ' Why it matters ')
    expect(built).toEqual({
      ok: true,
      payload: { url: page.href, title: 'A title', kind: 'page', html: page.full, note: 'Why it matters' },
    })
  })

  it('leaves the note out when it is empty, and cuts a long title and note', () => {
    const built = buildPayload({ ...page, title: 'x'.repeat(400) }, 'page', '   ')
    expect(built.ok && 'note' in built.payload).toBe(false)
    expect(built.ok && built.payload.title).toHaveLength(LIMITS.titleChars)
    const withLongNote = buildPayload(page, 'page', 'n'.repeat(900))
    expect(withLongNote.ok && withLongNote.payload.note).toHaveLength(LIMITS.noteChars)
  })

  it('recognises the built-in PDF viewer by its content type, even when the address does not end in .pdf', () => {
    const viewer = { href: 'https://arxiv.org/pdf/2005.14165', full: '<html><body><embed></body></html>', contentType: 'application/pdf' }
    expect(buildPayload(viewer, 'page')).toEqual({ ok: false, reason: 'pdf' })
    expect(buildPayload({ ...viewer, selectionText: 'x' }, 'selection')).toEqual({ ok: false, reason: 'pdf' })
    expect(buildPayload({ ...page, contentType: 'text/html' }, 'page').ok).toBe(true)
  })

  it('refuses an empty page', () => {
    expect(buildPayload({ href: page.href, full: '  ' }, 'page')).toEqual({ ok: false, reason: 'empty' })
  })

  it('sends a selection as its HTML, or as text when there is no HTML', () => {
    const rich = buildPayload({ ...page, selectionText: 'Hello', selectionHtml: '<b>Hello</b>' }, 'selection')
    expect(rich).toEqual({ ok: true, payload: { url: page.href, title: 'A title', kind: 'selection', html: '<b>Hello</b>' } })
    const plain = buildPayload({ ...page, selectionText: 'Hello', selectionHtml: '' }, 'selection')
    expect(plain).toEqual({ ok: true, payload: { url: page.href, title: 'A title', kind: 'selection', text: 'Hello' } })
  })

  it('never sends the whole page for a selection and refuses an empty selection', () => {
    const built = buildPayload({ ...page, selectionText: 'Hi', selectionHtml: '' }, 'selection')
    expect(built.ok && 'html' in built.payload).toBe(false)
    expect(buildPayload({ ...page, selectionText: '  ' }, 'selection')).toEqual({ ok: false, reason: 'no-selection' })
  })

  it('clips a selection over 2 MB of text', () => {
    const built = buildPayload({ ...page, selectionText: 'a'.repeat(LIMITS.textBytes + 50), selectionHtml: '' }, 'selection')
    expect(built.ok && built.payload.text).toHaveLength(LIMITS.textBytes)
  })
})

describe('talking to Spyglass', () => {
  it('posts JSON with the key in a header, without cookies, and returns the answer', async () => {
    const fetchImpl = answering(200, { item_id: 7, title: 'T', words: 300, replaced: false })
    const outcome = await sendToSpyglass({ address: ADDRESS, key: KEY, payload: { url: 'https://a.example/x' }, fetchImpl })
    expect(outcome).toEqual({ kind: 'ok', data: { item_id: 7, title: 'T', words: 300, replaced: false } })
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${ADDRESS}/api/radar/import/direct`)
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('omit')
    expect(init.headers).toMatchObject({ 'X-Spyglass-Key': KEY, 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body as string)).toEqual({ url: 'https://a.example/x' })
  })

  it('checks the connection with a GET and no body', async () => {
    const fetchImpl = answering(200, { ok: true })
    expect((await checkSpyglass({ address: ADDRESS, key: KEY, fetchImpl })).kind).toBe('ok')
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${ADDRESS}/api/radar/import/direct/check`)
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
  })

  it('sends nothing without a key', async () => {
    const fetchImpl = answering(200, {})
    expect(await sendToSpyglass({ address: ADDRESS, key: '', payload: {}, fetchImpl })).toEqual({ kind: 'no-key' })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('reports a refusal with its plain sentence', async () => {
    const outcome = await sendToSpyglass({ address: ADDRESS, key: KEY, payload: {}, fetchImpl: answering(400, { detail: 'No readable text was found in this page.' }) })
    expect(outcome).toEqual({ kind: 'http', status: 400, detail: 'No readable text was found in this page.' })
  })

  it('does not repeat a send that failed', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    expect(await sendToSpyglass({ address: ADDRESS, key: KEY, payload: {}, fetchImpl })).toEqual({ kind: 'network' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('gives up after the timeout', async () => {
    const hanging = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const outcome = await callSpyglass({ address: ADDRESS, key: KEY, path: '/x', method: 'GET', fetchImpl: hanging as unknown as typeof fetch, timeoutMs: 20 })
    expect(outcome).toEqual({ kind: 'timeout' })
    expect(hanging).toHaveBeenCalledTimes(1)
  })

  it('copes with an answer that is not JSON', async () => {
    const fetchImpl = vi.fn(async () => new Response('<html>oops</html>', { status: 502 }))
    expect(await sendToSpyglass({ address: ADDRESS, key: KEY, payload: {}, fetchImpl })).toEqual({ kind: 'http', status: 502, detail: '' })
  })
})

describe('describeOutcome', () => {
  const settings = "The key is missing or wrong. Open the extension's settings."

  it('says what happened in plain sentences', () => {
    expect(describeOutcome({ kind: 'ok', data: { replaced: false } })).toEqual({ ok: true, message: 'Added to Spyglass' })
    expect(describeOutcome({ kind: 'ok', data: { replaced: true } }).message).toBe('Updated in Spyglass')
    expect(describeOutcome({ kind: 'ok', data: {} }, 'check')).toEqual({ ok: true, message: 'Connected to Spyglass' })
    expect(describeOutcome({ kind: 'network' }).message).toBe('Spyglass is not running on this computer.')
    expect(describeOutcome({ kind: 'no-key' }).message).toBe(settings)
    expect(describeOutcome({ kind: 'http', status: 403, detail: 'The key is missing or wrong.' }).message).toBe(settings)
    expect(describeOutcome({ kind: 'timeout' }).message).toMatch(/did not answer within 30 seconds/)
  })

  it('tells the reader what to do when a page cannot be read', () => {
    expect(describeOutcome({ kind: 'unreadable' })).toEqual({ ok: false, message: 'This page cannot be read here.' })
    expect(describeOutcome({ kind: 'pdf' })).toEqual({
      ok: false,
      message: 'This page cannot be read here.',
      hint: 'Download the file and add it in Spyglass.',
    })
    expect(describeOutcome({ kind: 'no-selection' }).message).toBe('Select some text on the page first.')
  })

  it('maps the other answers from Spyglass', () => {
    expect(describeOutcome({ kind: 'http', status: 413, detail: '' }).message).toBe('This page is too large to send.')
    expect(describeOutcome({ kind: 'http', status: 429, detail: 'Wait a few minutes.' }).message).toBe('Wait a few minutes.')
    expect(describeOutcome({ kind: 'http', status: 400, detail: 'This page is larger than 15 MB.' }).message).toBe('This page is larger than 15 MB.')
    expect(describeOutcome({ kind: 'http', status: 400, detail: '' }).message).toBe('Spyglass could not add this page.')
    expect(describeOutcome({ kind: 'http', status: 500, detail: '' }).message).toBe('Spyglass had a problem adding this page.')
    expect(describeOutcome({ kind: 'http', status: 404, detail: '' }).message).toMatch(/too old/)
    expect(describeOutcome({ kind: 'surprise' }).ok).toBe(false)
  })
})

describe('the extension package', () => {
  it('has the same version as the app', () => {
    expect(extensionManifest.version).toBe(appManifest.version)
  })

  it('asks for only the local computer as a host', () => {
    expect(extensionManifest.host_permissions).toEqual(['http://localhost/*', 'http://127.0.0.1/*'])
  })
})
