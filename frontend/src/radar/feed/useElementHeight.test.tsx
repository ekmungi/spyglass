// Tests for useElementHeight: it reports the element's height, follows resizes, and is 0 where
// ResizeObserver does not exist.
import { act, cleanup, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useElementHeight } from './useElementHeight'

let callback: (() => void) | null = null
let disconnected = false
let height = 90

class FakeObserver {
  constructor(cb: () => void) {
    callback = cb
  }
  observe() {}
  disconnect() {
    disconnected = true
  }
}

function Probe() {
  const ref = useRef<HTMLDivElement>(null)
  const measured = useElementHeight(ref)
  return (
    <div ref={ref} data-testid="box">
      {measured}
    </div>
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  callback = null
  disconnected = false
  height = 90
})

describe('useElementHeight', () => {
  it('reports the height, follows a resize and stops watching on unmount', () => {
    vi.stubGlobal('ResizeObserver', FakeObserver)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ height }) as DOMRect)
    const view = render(<Probe />)
    expect(view.getByTestId('box').textContent).toBe('90')
    height = 126.4
    act(() => callback?.())
    expect(view.getByTestId('box').textContent).toBe('126')
    view.unmount()
    expect(disconnected).toBe(true)
  })

  it('is 0 where ResizeObserver does not exist', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const view = render(<Probe />)
    expect(view.getByTestId('box').textContent).toBe('0')
  })
})
