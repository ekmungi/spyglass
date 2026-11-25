// Tests for useSteadyHeight: a paged list keeps the height of the tallest page it has shown, and forgets
// it on a window resize. jsdom does no layout, so the measured element's height is stubbed from its rows.
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSteadyHeight } from './useSteadyHeight'

/** The stubbed height of one row, in pixels. */
const ROW = 100

/** A paged list: `rows` rows inside a measured list, wrapped in the container that takes the min-height. */
function Harness({ page, rows }: { page: number; rows: number }) {
  const { ref, minHeight } = useSteadyHeight<HTMLUListElement>(page)
  return (
    <div data-testid="container" style={{ minHeight }}>
      <ul ref={ref}>
        {Array.from({ length: rows }, (_, index) => (
          <li key={index} />
        ))}
      </ul>
    </div>
  )
}

const container = () => document.querySelector<HTMLElement>('[data-testid="container"]')!

beforeEach(() => {
  // A list is as tall as its rows; every other element has no height, as in jsdom.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const height = this.tagName === 'UL' ? this.children.length * ROW : 0
    return { height, width: 0, top: 0, left: 0, right: 0, bottom: height, x: 0, y: 0, toJSON: () => ({}) }
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('useSteadyHeight', () => {
  it('keeps the height of the first page when a shorter page follows', () => {
    const { rerender } = render(<Harness page={0} rows={5} />)
    expect(container().style.minHeight).toBe('500px')
    rerender(<Harness page={1} rows={2} />)
    expect(container().style.minHeight).toBe('500px')
  })

  it('grows to a page that is taller than any seen', () => {
    const { rerender } = render(<Harness page={0} rows={3} />)
    rerender(<Harness page={1} rows={5} />)
    expect(container().style.minHeight).toBe('500px')
    rerender(<Harness page={2} rows={4} />)
    expect(container().style.minHeight).toBe('500px')
  })

  it('forgets the stored height on a window resize and measures the current page again', () => {
    const { rerender } = render(<Harness page={0} rows={5} />)
    rerender(<Harness page={1} rows={2} />)
    expect(container().style.minHeight).toBe('500px')
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    expect(container().style.minHeight).toBe('200px')
  })

  it('stops listening for resizes once the list is gone', () => {
    const remove = vi.spyOn(window, 'removeEventListener')
    const { unmount } = render(<Harness page={0} rows={2} />)
    unmount()
    expect(remove).toHaveBeenCalledWith('resize', expect.any(Function))
  })
})
