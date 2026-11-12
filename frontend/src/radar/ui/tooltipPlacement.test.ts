// Tests for tooltip placement: a bubble that would run past its clipping area slides back inside,
// and one that fits stays centred.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { placeBubble } from './tooltipPlacement'

function rect(left: number, width: number): DOMRect {
  return { left, right: left + width, width, top: 0, bottom: 20, height: 20, x: left, y: 0, toJSON: () => ({}) } as DOMRect
}

/** A clipping column 0..600 holding a bubble at the given place. */
function setUp(bubbleLeft: number, bubbleWidth: number) {
  const column = document.createElement('div')
  column.style.overflowX = 'hidden'
  const bubble = document.createElement('span')
  column.appendChild(bubble)
  document.body.appendChild(column)
  Object.defineProperty(column, 'clientWidth', { configurable: true, value: 600 })
  vi.spyOn(column, 'getBoundingClientRect').mockReturnValue(rect(0, 600))
  vi.spyOn(bubble, 'getBoundingClientRect').mockReturnValue(rect(bubbleLeft, bubbleWidth))
  return bubble
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('placeBubble', () => {
  it('leaves a bubble that fits where it is', () => {
    const bubble = setUp(200, 120)
    expect(placeBubble(bubble)).toBe(0)
    expect(bubble.style.getPropertyValue('--tip-dx')).toBe('0px')
  })

  it('slides a bubble back from the right edge of its column', () => {
    const bubble = setUp(540, 120)
    // 660 would end past 600 - 6.
    expect(placeBubble(bubble)).toBe(-66)
    expect(bubble.style.getPropertyValue('--tip-dx')).toBe('-66px')
  })

  it('slides a bubble in from the left edge', () => {
    const bubble = setUp(-30, 120)
    expect(placeBubble(bubble)).toBe(36)
  })
})
