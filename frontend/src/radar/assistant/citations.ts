// citations: the [#123] markers in a feed answer. `citedIds` lists the items an answer cites, in the
// order it first cites them; `remarkCitations` turns each marker (and only that exact form) into a
// link node tagged with `data-cite`, which AnswerMarkdown renders as a link to the item.
import type { RetrievedItem } from '../api/types'

const MARKER = /\[#(\d{1,9})\]/g

/** The item ids an answer cites, each once, in the order of first mention. */
export function citedIds(text: string): number[] {
  const seen: number[] = []
  for (const match of text.matchAll(MARKER)) {
    const id = Number(match[1])
    if (id > 0 && !seen.includes(id)) seen.push(id)
  }
  return seen
}

/** The headline for an id from the thread's retrieved set, or null when it is not known. */
export function headlineFrom(retrieved: RetrievedItem[], id: number): string | null {
  return retrieved.find((entry) => entry.id === id)?.headline || null
}

/** Just enough of the markdown syntax tree for the citation pass. */
interface MdNode {
  type: string
  value?: string
  url?: string
  children?: MdNode[]
  data?: { hProperties?: Record<string, string> }
}

// Nodes whose text is not prose: a marker inside code or inside an existing link stays as written.
const SKIP = new Set(['link', 'linkReference', 'image', 'imageReference', 'code', 'inlineCode'])

/** The nodes that replace one text node: its text pieces with a link where a marker stood. */
function split(value: string, label: (id: number) => string | null): MdNode[] {
  const out: MdNode[] = []
  let last = 0
  for (const match of value.matchAll(MARKER)) {
    const id = Number(match[1])
    if (id <= 0) continue
    if (match.index > last) out.push({ type: 'text', value: value.slice(last, match.index) })
    out.push({
      type: 'link',
      url: `#/item/${id}`,
      children: [{ type: 'text', value: label(id) ?? `#${id}` }],
      data: { hProperties: { 'data-cite': String(id) } },
    })
    last = match.index + match[0].length
  }
  if (!out.length) return [{ type: 'text', value }]
  if (last < value.length) out.push({ type: 'text', value: value.slice(last) })
  return out
}

/** Walk the tree and replace markers in text nodes, in place (the usual way for a remark plugin). */
function walk(node: MdNode, label: (id: number) => string | null): void {
  if (!node.children || SKIP.has(node.type)) return
  node.children = node.children.flatMap((child) => (child.type === 'text' && child.value ? split(child.value, label) : [child]))
  node.children.forEach((child) => walk(child, label))
}

/** A remark plugin: `[#123]` becomes a link tagged `data-cite="123"` that shows `label(123)` (or "#123"). */
export function remarkCitations(options: { label: (id: number) => string | null }) {
  return (tree: MdNode) => walk(tree, options.label)
}
