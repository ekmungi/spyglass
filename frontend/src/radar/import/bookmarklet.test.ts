import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACK_MESSAGE, MAX_BOOKMARKLET_LENGTH, PAGE_MESSAGE, buildBookmarklet, encodeForBookmark, isUsableKey, isUsableOrigin, minify } from './bookmarklet'

const ORIGIN = 'http://localhost:7778'
const KEY = '0123456789abcdef0123456789abcdef'

/** The script a browser runs for the link: everything after "javascript:", percent-decoded. */
function scriptOf(link: string): string {
  return decodeURIComponent(link.slice('javascript:'.length))
}

describe('buildBookmarklet', () => {
  it('stays under 2,000 characters', () => {
    const link = buildBookmarklet(ORIGIN, KEY)
    expect(link.startsWith('javascript:')).toBe(true)
    expect(link.length).toBeLessThan(MAX_BOOKMARKLET_LENGTH)
    expect(buildBookmarklet('http://127.0.0.1:65535', KEY).length).toBeLessThan(MAX_BOOKMARKLET_LENGTH)
  })

  it('contains no character that breaks a bookmark', () => {
    const link = buildBookmarklet(ORIGIN, KEY)
    expect(link).toMatch(/^javascript:[A-Za-z0-9\-_.~!$&'()*+,;=:@/?[\]%]+$/)
    expect(link).not.toMatch(/[\s#"<>{}|\\^`]/)
    // Every % starts a complete escape, so the browser decodes the script exactly.
    expect(link).not.toMatch(/%(?![0-9A-F]{2})/)
  })

  it('decodes to valid JavaScript that names the Spyglass origin', () => {
    const script = scriptOf(buildBookmarklet(ORIGIN, KEY))
    expect(() => new Function(script)).not.toThrow()
    expect(script).toContain(`'${ORIGIN}'`)
    expect(script).not.toContain('SPYGLASS_ORIGIN')
    expect(script).not.toContain('SPYGLASS_KEY')
    expect(script).toContain(`'${KEY}'`)
    expect(script).toContain(PAGE_MESSAGE)
    expect(script).toContain(ACK_MESSAGE)
  })

  it('refuses an origin that is not plain http(s)', () => {
    for (const bad of ['javascript:alert(1)', "http://x'+alert(1)+'", 'http://localhost:7778/path', 'file://', '']) {
      expect(isUsableOrigin(bad)).toBe(false)
      expect(() => buildBookmarklet(bad, KEY)).toThrow()
    }
    expect(isUsableOrigin('http://[::1]:7778')).toBe(true)
  })

  it('refuses a key that is not 32 hex characters, so nothing can be smuggled into the script', () => {
    for (const bad of ['', 'abc', KEY.toUpperCase(), `${KEY}'+alert(1)+'`, 'g'.repeat(32), `${KEY}0`]) {
      expect(isUsableKey(bad)).toBe(false)
      expect(() => buildBookmarklet(ORIGIN, bad)).toThrow()
    }
    expect(isUsableKey(KEY)).toBe(true)
  })
})

describe('minify and encodeForBookmark', () => {
  it('drops comments and spaces but keeps strings and needed spaces', () => {
    const code = "/* head */ var a = 'x // y /* z */';\n// line\nif (a) { return typeof a; }"
    expect(minify(code)).toBe("var a='x // y /* z */';if(a){return typeof a;}")
  })

  it('keeps a space before a string that follows a word', () => {
    expect(minify("return 'a';")).toBe("return 'a';")
    expect(minify("x = ['a', 'b']")).toBe("x=['a','b']")
  })

  it('encodes the risky characters', () => {
    expect(encodeForBookmark('a b#c%d"e{f}')).toBe('a%20b%23c%25d%22e%7Bf%7D')
  })
})

describe('the button on a page', () => {
  let opened: { postMessage: ReturnType<typeof vi.fn>; closed: boolean } | null
  let openSpy: ReturnType<typeof vi.spyOn>
  let submitSpy: ReturnType<typeof vi.spyOn>

  const run = () => new Function(scriptOf(buildBookmarklet(ORIGIN, KEY)))()

  beforeEach(() => {
    vi.useFakeTimers()
    document.title = 'A story behind a paywall'
    document.body.innerHTML = '<article><h1>A story</h1><p>Text the reader can see.</p></article>'
    opened = { postMessage: vi.fn(), closed: false }
    openSpy = vi.spyOn(window, 'open').mockImplementation(() => opened as unknown as Window)
    submitSpy = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('opens the import window and sends the page to the Spyglass origin only', () => {
    run()
    expect(openSpy).toHaveBeenCalledWith(`${ORIGIN}/#/import`, 'spyglass_import', expect.stringContaining('popup'))
    vi.advanceTimersByTime(260)
    expect(opened!.postMessage).toHaveBeenCalledTimes(1)
    const [message, target] = opened!.postMessage.mock.calls[0]
    expect(target).toBe(ORIGIN)
    expect(message).toMatchObject({ type: PAGE_MESSAGE, url: window.location.href, title: 'A story behind a paywall', key: KEY })
    expect(message.html).toContain('Text the reader can see.')
    vi.advanceTimersByTime(500)
    expect(opened!.postMessage).toHaveBeenCalledTimes(3)
  })

  it('stops sending once Spyglass answers, and never falls back to the form', () => {
    run()
    vi.advanceTimersByTime(260)
    window.dispatchEvent(new MessageEvent('message', { origin: ORIGIN, data: { type: ACK_MESSAGE } }))
    vi.advanceTimersByTime(4000)
    expect(opened!.postMessage).toHaveBeenCalledTimes(1)
    expect(submitSpy).not.toHaveBeenCalled()
  })

  it('ignores an answer from any other origin', () => {
    run()
    window.dispatchEvent(new MessageEvent('message', { origin: 'https://evil.example', data: { type: ACK_MESSAGE } }))
    vi.advanceTimersByTime(1000)
    expect(opened!.postMessage).toHaveBeenCalledTimes(4)
  })

  it('posts the page as a form into the same window after 3 seconds without an answer', () => {
    run()
    vi.advanceTimersByTime(3000)
    expect(submitSpy).toHaveBeenCalledTimes(1)
    const form = document.querySelector('form') as HTMLFormElement
    expect(form.action).toBe(`${ORIGIN}/api/radar/import/stage`)
    expect(form.method).toBe('post')
    expect(form.enctype).toBe('multipart/form-data')
    expect(form.target).toBe('spyglass_import')
    expect(form.acceptCharset).toBe('UTF-8')
    const fields = Object.fromEntries(Array.from(form.elements as HTMLFormControlsCollection, (el) => [(el as HTMLInputElement).name, (el as HTMLInputElement).value]))
    expect(Object.keys(fields)).toEqual(['url', 'title', 'html', 'key'])
    expect(fields.key).toBe(KEY)
    expect(fields.html).toContain('Text the reader can see.')
    const sent = opened!.postMessage.mock.calls.length
    vi.advanceTimersByTime(1000)
    expect(opened!.postMessage).toHaveBeenCalledTimes(sent)
  })

  it('says so when the browser blocks the window', () => {
    openSpy.mockImplementation(() => null)
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    run()
    vi.advanceTimersByTime(4000)
    expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining('blocked'))
    expect(submitSpy).not.toHaveBeenCalled()
  })
})
