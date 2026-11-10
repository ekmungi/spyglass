// Tests for pure window-mode helpers: args builder and browser-path resolver.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { buildAppWindowArgs, resolveBrowserPath } from './window-mode'

describe('buildAppWindowArgs', () => {
  it('wraps the url in the --app flag', () => {
    expect(buildAppWindowArgs('http://127.0.0.1:7777/')).toEqual(['--app=http://127.0.0.1:7777/'])
  })
})

describe('resolveBrowserPath', () => {
  it('returns the custom path when it exists', () => {
    const result = resolveBrowserPath('custom', 'C:/x/my.exe', (p) => p === 'C:/x/my.exe')
    expect(result).toBe('C:/x/my.exe')
  })

  it('returns null for custom when the path does not exist', () => {
    const result = resolveBrowserPath('custom', 'C:/x/my.exe', () => false)
    expect(result).toBeNull()
  })

  it('returns the first matching known chrome path', () => {
    const result = resolveBrowserPath(
      'chrome',
      '',
      (p) => p === 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    )
    expect(result).toBe('C:/Program Files/Google/Chrome/Application/chrome.exe')
  })

  it('returns null when no edge path exists', () => {
    const result = resolveBrowserPath('edge', '', () => false)
    expect(result).toBeNull()
  })

  describe('LOCALAPPDATA fallback for chrome', () => {
    let savedLocalAppData: string | undefined

    beforeEach(() => {
      savedLocalAppData = process.env.LOCALAPPDATA
    })

    afterEach(() => {
      if (savedLocalAppData === undefined) {
        delete process.env.LOCALAPPDATA
      } else {
        process.env.LOCALAPPDATA = savedLocalAppData
      }
    })

    it('resolves the per-user chrome install from LOCALAPPDATA when only that path exists', () => {
      process.env.LOCALAPPDATA = 'C:\\Users\\TestUser\\AppData\\Local'
      const expected = 'C:/Users/TestUser/AppData/Local/Google/Chrome/Application/chrome.exe'
      const result = resolveBrowserPath('chrome', '', (p) => p === expected)
      expect(result).toBe(expected)
    })
  })
})
