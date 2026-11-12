// Tests for safeUrl: only plain http(s) addresses may become links or be opened.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openExternal, safeHttpUrl } from './safeUrl'

afterEach(() => vi.restoreAllMocks())

describe('safeHttpUrl', () => {
  it('passes http and https addresses', () => {
    expect(safeHttpUrl('https://example.org/a?b=1')).toBe('https://example.org/a?b=1')
    expect(safeHttpUrl('  http://example.org/x  ')).toBe('http://example.org/x')
  })

  it('rejects every other scheme, relative paths and empty values', () => {
    for (const bad of ['javascript:alert(1)', ' JaVaScRiPt:alert(1)', 'java\tscript:alert(1)', 'data:text/html,<b>x</b>', 'file:///etc/passwd', 'vbscript:x', '//example.org/x', '/relative', 'not a url', '', '   ']) {
      expect(safeHttpUrl(bad)).toBeNull()
    }
    expect(safeHttpUrl(null)).toBeNull()
    expect(safeHttpUrl(undefined)).toBeNull()
    expect(safeHttpUrl(42 as unknown as string)).toBeNull()
  })
})

describe('openExternal', () => {
  it('opens a safe address with noopener', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openExternal('https://example.org/x')).toBe(true)
    expect(open).toHaveBeenCalledWith('https://example.org/x', '_blank', 'noopener,noreferrer')
  })

  it('opens nothing for an unsafe address', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openExternal('javascript:alert(1)')).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })
})
