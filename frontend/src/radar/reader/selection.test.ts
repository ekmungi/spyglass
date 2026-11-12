// Tests for selection -> ask: reading the selection, placing the toolbar, and turning a choice
// into a quote or an immediate message.
import { describe, expect, it } from 'vitest'
import { getSelectionInfo, MAX_SELECTION, selectionRequest, toolbarPosition, type SelectionLike } from './selection'

const RECT = { top: 300, left: 200, width: 120, height: 20, bottom: 320 }

/** A fake selection whose range lives under `node`. */
function fakeSelection(text: string, node: Node, collapsed = false): SelectionLike {
  return {
    isCollapsed: collapsed,
    rangeCount: 1,
    toString: () => text,
    getRangeAt: () => ({ commonAncestorContainer: node, getBoundingClientRect: () => RECT }),
  }
}

describe('getSelectionInfo', () => {
  const container = document.createElement('div')
  const inside = document.createElement('p')
  container.appendChild(inside)
  const outside = document.createElement('p')

  it('returns the trimmed, whitespace-collapsed text and its box', () => {
    const info = getSelectionInfo(fakeSelection('  the flat-rate\n   pricing  ', inside), container)
    expect(info).toEqual({ text: 'the flat-rate pricing', rect: RECT })
  })

  it('ignores collapsed, empty, short or outside selections', () => {
    expect(getSelectionInfo(null, container)).toBeNull()
    expect(getSelectionInfo(fakeSelection('long enough', inside, true), container)).toBeNull()
    expect(getSelectionInfo(fakeSelection('ab', inside), container)).toBeNull()
    expect(getSelectionInfo(fakeSelection('outside the document', outside), container)).toBeNull()
    expect(getSelectionInfo({ ...fakeSelection('text', inside), rangeCount: 0 }, container)).toBeNull()
  })

  it('cuts very long selections with an ellipsis', () => {
    const info = getSelectionInfo(fakeSelection('x'.repeat(MAX_SELECTION + 500), inside), container)
    expect(info?.text.length).toBeLessThanOrEqual(MAX_SELECTION)
    expect(info?.text.endsWith('…')).toBe(true)
  })
})

describe('toolbarPosition', () => {
  const layer = { top: 0, left: 100, width: 800 }

  it('centres the toolbar above the selection, accounting for scroll', () => {
    const position = toolbarPosition(RECT, layer, 1000)
    expect(position.below).toBe(false)
    expect(position.left).toBe(160) // 200 - 100 + 120 / 2
    expect(position.top).toBeLessThan(RECT.top + 1000)
  })

  it('anchors the toolbar a gap above the first selected line, never on it', () => {
    const position = toolbarPosition(RECT, layer, 0)
    expect(position.below).toBe(false)
    expect(position.top).toBe(RECT.top - 12)
  })

  it('flips below the selection near the top of the view', () => {
    const position = toolbarPosition({ ...RECT, top: 60, bottom: 80 }, layer, 0)
    expect(position.below).toBe(true)
    expect(position.top).toBeGreaterThan(80)
  })

  it('keeps the toolbar inside the column', () => {
    expect(toolbarPosition({ ...RECT, left: 100, width: 4 }, layer, 0).left).toBeGreaterThanOrEqual(96)
    expect(toolbarPosition({ ...RECT, left: 895, width: 4 }, layer, 0).left).toBeLessThanOrEqual(800 - 96)
  })
})

describe('selectionRequest', () => {
  it('Ask attaches a quote for the composer', () => {
    expect(selectionRequest('ask', 'a passage')).toEqual({ kind: 'quote', text: 'a passage' })
  })

  it('Explain sends the explain preset with the passage', () => {
    expect(selectionRequest('explain', 'a passage')).toEqual({ kind: 'send', send: { content: '', action: 'explain', selection: 'a passage' } })
  })

  it('Why is this so? sends the question with the passage', () => {
    expect(selectionRequest('why', 'a passage')).toEqual({ kind: 'send', send: { content: 'Why is this so?', selection: 'a passage' } })
  })
})
