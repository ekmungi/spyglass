// Highlight body marks: a rehype plugin that wraps saved quotes in
// <mark data-hid> elements inside the rendered markdown, plus offset helpers.

export interface MarkSpec {
  id: number
  quote: string
}

// Minimal hast shapes; kept local so no extra type packages are needed.
interface TextNode {
  type: 'text'
  value: string
}
interface ElementNode {
  type: string
  tagName?: string
  properties?: Record<string, unknown>
  children?: HastNode[]
}
type HastNode = TextNode | ElementNode

/** Wrap the first single-text-node occurrence of a quote in a mark element.
 * Quotes spanning styled segments will not match one text node; those fall
 * back to the highlights list only -- an accepted limitation. */
function markQuote(node: ElementNode, spec: MarkSpec): boolean {
  const children = node.children
  if (!children) {
    return false
  }
  for (let i = 0; i < children.length; i += 1) {
    const child = children[i]
    if (child.type === 'text') {
      const text = (child as TextNode).value
      const at = text.indexOf(spec.quote)
      if (at >= 0) {
        const replacement: HastNode[] = []
        if (at > 0) {
          replacement.push({ type: 'text', value: text.slice(0, at) })
        }
        replacement.push({
          type: 'element',
          tagName: 'mark',
          properties: { 'data-hid': String(spec.id) },
          children: [{ type: 'text', value: spec.quote }],
        })
        if (at + spec.quote.length < text.length) {
          replacement.push({ type: 'text', value: text.slice(at + spec.quote.length) })
        }
        children.splice(i, 1, ...replacement)
        return true
      }
    } else if (markQuote(child as ElementNode, spec)) {
      return true
    }
  }
  return false
}

/** Rehype plugin factory: marks each saved highlight once in the rendered tree. */
export function rehypeHighlights(highlights?: MarkSpec[]) {
  return (tree: unknown) => {
    for (const spec of highlights ?? []) {
      markQuote(tree as ElementNode, spec)
    }
  }
}

/** Char offsets of a quote inside the stored markdown; nulls when not verbatim. */
export function findOffsets(
  markdown: string,
  quote: string,
): { start: number | null; end: number | null } {
  const at = markdown.indexOf(quote)
  if (at < 0) {
    return { start: null, end: null }
  }
  return { start: at, end: at + quote.length }
}
