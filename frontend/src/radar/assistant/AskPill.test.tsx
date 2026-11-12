// The Ask pill: shown only when the page's own Ask button has scrolled out of view and the panel
// is closed; hidden pills are unfocusable; without IntersectionObserver it never shows.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AskPill } from './AskPill'
import { pillVisible, useAskPill } from './useAskPill'
import { setAssistOpen } from './assistStore'

/** A stand-in for IntersectionObserver that the test can fire by hand. */
class FakeObserver {
  static all: FakeObserver[] = []
  observed: Element[] = []
  disconnected = false
  private readonly callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    FakeObserver.all.push(this)
  }
  observe(element: Element) {
    this.observed.push(element)
  }
  disconnect() {
    this.disconnected = true
  }
  fire(isIntersecting: boolean) {
    this.callback([{ isIntersecting, target: this.observed[0] } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
  }
}
const live = () => FakeObserver.all.filter((observer) => !observer.disconnected).at(-1) as FakeObserver

function Harness({ active = true, onAsk = () => undefined }: { active?: boolean; onAsk?: () => void }) {
  const { watchButton, shown } = useAskPill('today', active)
  return (
    <>
      <button ref={watchButton}>Ask about today</button>
      <AskPill label="Ask about today" shown={shown} onClick={onAsk} />
    </>
  )
}

/** The pill's button, found even while it is hidden from the accessibility tree. */
const pill = () => document.querySelector('.r-askpill') as HTMLButtonElement

beforeEach(() => {
  FakeObserver.all = []
  vi.stubGlobal('IntersectionObserver', FakeObserver)
  window.localStorage.clear()
  setAssistOpen('today', false)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  setAssistOpen('today', false)
})

describe('pillVisible', () => {
  it('needs the button out of view, the panel closed and the page showing', () => {
    expect(pillVisible(true, false, true)).toBe(true)
    expect(pillVisible(false, false, true)).toBe(false)
    expect(pillVisible(true, true, true)).toBe(false)
    expect(pillVisible(true, false, false)).toBe(false)
  })
})

describe('AskPill with the page button', () => {
  it('is hidden and unfocusable at first, then shown once the button scrolls out of view, and hidden again when it returns', () => {
    render(<Harness />)
    expect(pill().dataset.shown).toBe('false')
    expect(pill()).toHaveAttribute('tabindex', '-1')
    expect(pill()).toHaveAttribute('aria-hidden', 'true')
    expect(live().observed).toEqual([screen.getByRole('button', { name: 'Ask about today' })])
    act(() => live().fire(false))
    expect(pill().dataset.shown).toBe('true')
    expect(pill()).toHaveAttribute('tabindex', '0')
    expect(pill()).not.toHaveAttribute('aria-hidden')
    act(() => live().fire(true))
    expect(pill().dataset.shown).toBe('false')
  })

  it('is hidden while the assistant panel is open, and returns when it is closed', () => {
    render(<Harness />)
    act(() => live().fire(false))
    expect(pill().dataset.shown).toBe('true')
    act(() => setAssistOpen('today', true))
    expect(pill().dataset.shown).toBe('false')
    act(() => setAssistOpen('today', false))
    expect(pill().dataset.shown).toBe('true')
  })

  it('stays hidden while its page is under the reader', () => {
    render(<Harness active={false} />)
    act(() => live().fire(false))
    expect(pill().dataset.shown).toBe('false')
  })

  it('calls onAsk when clicked', () => {
    const onAsk = vi.fn()
    render(<Harness onAsk={onAsk} />)
    act(() => live().fire(false))
    fireEvent.click(pill())
    expect(onAsk).toHaveBeenCalledTimes(1)
  })

  it('never shows without IntersectionObserver', () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    render(<Harness />)
    expect(pill().dataset.shown).toBe('false')
  })

  it('stops watching when the page goes away', () => {
    const { unmount } = render(<Harness />)
    const observer = live()
    unmount()
    expect(observer.disconnected).toBe(true)
  })
})
