// Parser for the card:<id> link scheme used inside Daily Brief markdown.

// Matches the target of a markdown link written as [label](card:123). Anchored on the
// closing bracket so parenthetical prose like "(card: helpful)" inside text or link
// labels can never produce a phantom id.
const CARD_LINK = /\]\(card:(\d+)\)/g

// Matches a full [title](card:id) link, capturing the title text. The title group
// tolerates escaped brackets (\[ \]) so a renderer-escaped title like "Foo \[bar\]"
// is captured whole rather than truncated at the first literal bracket.
const CARD_LINK_WITH_TITLE = /\[((?:\\.|[^\]\\])*)\]\(card:(\d+)\)/g

/** Extract the unique card ids referenced by card:<id> links, in order of appearance.
 * Non-card links and plain text are ignored; returns [] when none exist. */
export function parseCardIds(markdown: string): number[] {
  const seen = new Set<number>()
  const ids: number[] = []
  for (const match of markdown.matchAll(CARD_LINK)) {
    const id = Number(match[1])
    if (!seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }
  return ids
}

/** Extract [title](card:id) links as {id, title}, deduped by id (first title wins),
 * in order of appearance. Tolerates renderer-escaped brackets in the title (\[ \])
 * and unescapes them back to plain [ / ]. Used where a human-readable label is
 * needed alongside the id (e.g. removable chips for a bullet's related cards). */
export function parseCardLinks(markdown: string): { id: number; title: string }[] {
  const seen = new Set<number>()
  const links: { id: number; title: string }[] = []
  for (const match of markdown.matchAll(CARD_LINK_WITH_TITLE)) {
    const id = Number(match[2])
    if (seen.has(id)) continue
    seen.add(id)
    const title = match[1].replace(/\\\[/g, '[').replace(/\\\]/g, ']')
    links.push({ id, title })
  }
  return links
}
