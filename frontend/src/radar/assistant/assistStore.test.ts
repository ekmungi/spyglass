// Tests for where the assistant panel starts: closed on a narrow window, as remembered on a wide one.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const original = window.innerWidth

function setWidth(width: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
}

/** A fresh copy of the store, as if the page had just loaded at the current width. */
async function freshStore() {
  vi.resetModules()
  return import('./assistStore')
}

beforeEach(() => {
  window.localStorage.clear()
  window.localStorage.setItem('radar.assist.open', JSON.stringify({ reader: true, today: true }))
})

afterEach(() => setWidth(original))

describe('assistant panel at start-up', () => {
  it('starts closed below 1000px even when it was left open, so it does not cover the reader', async () => {
    setWidth(800)
    const store = await freshStore()
    expect(store.getAssistState().open).toEqual({ reader: false, today: false, feed: false })
  })

  it('keeps the remembered state on a wide window', async () => {
    setWidth(1280)
    const store = await freshStore()
    expect(store.getAssistState().open).toEqual({ reader: true, today: true, feed: false })
  })

  it('opens when asked on a narrow window, without making that the remembered state', async () => {
    setWidth(800)
    const store = await freshStore()
    store.setAssistOpen('reader', true)
    expect(store.getAssistState().open.reader).toBe(true)
    expect(JSON.parse(window.localStorage.getItem('radar.assist.open') ?? '{}')).toEqual({ reader: true, today: true })
  })

  it('closes when the window is made narrower than the breakpoint', async () => {
    setWidth(1280)
    const store = await freshStore()
    setWidth(700)
    window.dispatchEvent(new Event('resize'))
    expect(store.getAssistState().open).toEqual({ reader: false, today: false, feed: false })
  })
})
