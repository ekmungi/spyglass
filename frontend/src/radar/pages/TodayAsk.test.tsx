// Today wires the Ask pill to the masthead button: scroll the button away and the pill appears;
// clicking it opens the assistant panel for today's brief, which hides the pill again.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getAssistState, setAssistOpen } from '../assistant/assistStore'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { TodayPage } from './TodayPage'

const observers: { target: Element; callback: IntersectionObserverCallback }[] = []

class FakeObserver {
  private readonly callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
  }
  observe(target: Element) {
    observers.push({ target, callback: this.callback })
  }
  disconnect() {
    /* nothing to release */
  }
}

beforeEach(() => {
  observers.length = 0
  vi.stubGlobal('IntersectionObserver', FakeObserver)
  resetMockState()
  clearResourceCache()
  window.localStorage.clear()
  window.history.replaceState(null, '', '/#/today')
  setAssistOpen('today', false)
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  vi.unstubAllGlobals()
  setAssistOpen('today', false)
})

describe('Today Ask pill', () => {
  it('appears when the masthead button scrolls out of view and opens the panel for the brief', async () => {
    render(<TodayPage />)
    const button = await screen.findByRole('button', { name: 'Ask about today' }, { timeout: 4000 })
    const pill = document.querySelector('.r-askpill') as HTMLButtonElement
    expect(pill.dataset.shown).toBe('false')
    const watcher = observers.find((entry) => entry.target === button)
    expect(watcher).toBeDefined()
    act(() => watcher?.callback([{ isIntersecting: false, target: button } as unknown as IntersectionObserverEntry], {} as IntersectionObserver))
    expect(pill.dataset.shown).toBe('true')
    fireEvent.click(pill)
    expect(getAssistState().open.today).toBe(true)
    expect(getAssistState().target).toEqual({ kind: 'brief', day: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) })
    expect(pill.dataset.shown).toBe('false')
  })
})
