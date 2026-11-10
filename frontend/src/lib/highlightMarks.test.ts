// Tests for the highlight mark plugin: hast text nodes wrapped in <mark>.
import { describe, expect, it } from 'vitest'
import { findOffsets, rehypeHighlights } from './highlightMarks'

type Node = Record<string, unknown>

function paragraph(text: string): Node {
  return {
    type: 'root',
    children: [
      { type: 'element', tagName: 'p', properties: {}, children: [{ type: 'text', value: text }] },
    ],
  }
}

describe('rehypeHighlights', () => {
  it('wraps a matching quote in a mark element carrying the highlight id', () => {
    const tree = paragraph('the memory eviction policy matters most')
    rehypeHighlights([{ id: 3, quote: 'memory eviction policy' }])(tree)
    const children = (
      (tree.children as Node[])[0] as { children: Node[] }
    ).children
    expect(children).toHaveLength(3)
    expect(children[0]).toMatchObject({ type: 'text', value: 'the ' })
    expect(children[1]).toMatchObject({
      type: 'element',
      tagName: 'mark',
      properties: { 'data-hid': '3' },
    })
    expect((children[1] as { children: Node[] }).children[0]).toMatchObject({
      value: 'memory eviction policy',
    })
    expect(children[2]).toMatchObject({ type: 'text', value: ' matters most' })
  })

  it('leaves the tree untouched when the quote is not found in one text node', () => {
    const tree = paragraph('nothing to see here')
    rehypeHighlights([{ id: 1, quote: 'absent quote' }])(tree)
    expect(((tree.children as Node[])[0] as { children: Node[] }).children).toHaveLength(1)
  })

  it('marks each highlight only once', () => {
    const tree = paragraph('repeat repeat')
    rehypeHighlights([{ id: 1, quote: 'repeat' }])(tree)
    const children = ((tree.children as Node[])[0] as { children: Node[] }).children
    const marks = children.filter((c) => (c as { tagName?: string }).tagName === 'mark')
    expect(marks).toHaveLength(1)
  })
})

describe('findOffsets', () => {
  it('returns the char range of the quote inside the markdown', () => {
    expect(findOffsets('abc memory xyz', 'memory')).toEqual({ start: 4, end: 10 })
  })

  it('returns nulls when the quote does not occur verbatim', () => {
    expect(findOffsets('abc', 'zzz')).toEqual({ start: null, end: null })
  })
})
