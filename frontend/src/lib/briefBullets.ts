// Parses a Daily Brief's rendered narrative markdown into structured sections + bullets
// so bullets can be grip-selected and each bullet's
// card ids read client-side without any change to the Brief backend model. Input is expected
// to be `splitBrief(markdown).narrative` from briefSections.ts (References / Also noticed
// tails already stripped).

import { parseCardLinks } from './briefLinks'

// A line matching `^## ` starts a new theme section; heading text is the rest of the line.
const SECTION_HEADING = /^## (.*)$/
// A line matching `^- ` (no leading whitespace) starts a new bullet; its markdown is
// everything after the "- " prefix.
const BULLET_LINE = /^- (.*)$/
// A line matching exactly two leading spaces then "- Related: " is a sub-line belonging
// to the most recently seen bullet, not a bullet of its own.
const RELATED_LINE = /^ {2}- Related: (.*)$/

/** One bullet's parsed shape: its prose (with inline card: links intact), the cards it
 * cites inline (deduped by id), and the related cards from its "Related:" sub-line
 * (deduped by id). Titles are kept on `related` because the session popover renders them as
 * removable chips that need a label, not just an id. */
export interface Bullet {
  markdown: string
  cards: { id: number; title: string }[]
  related: { id: number; title: string }[]
}

/** A theme section: its heading text and the bullets under it (possibly empty). */
export interface BriefSection {
  heading: string
  bullets: Bullet[]
}

/** The full parsed brief: the overview prose before the first heading, plus sections. */
export interface ParsedBrief {
  overview: string
  sections: BriefSection[]
}

/** Build a new bullet from a bullet line's markdown. Cards come from inline links;
 * related starts empty and is filled in by a following Related sub-line, if any. */
function makeBullet(markdown: string): Bullet {
  return { markdown, cards: parseCardLinks(markdown), related: [] }
}

/** One bullet's stable key within a render — sections/bullets never reorder
 * mid-render — so `${sectionIndex}:${bulletIndex}` is enough to identify it.
 * Centralized here so BriefNarrative and BriefReader share one scheme
 * instead of duplicating the template string. */
export function bulletKey(sectionIndex: number, bulletIndex: number): string {
  return `${sectionIndex}:${bulletIndex}`
}

/** Parse rendered brief narrative markdown into an overview string plus an ordered list
 * of sections, each with its bullets. Pure function, no mutation of the input string. */
export function parseBriefBullets(narrative: string): ParsedBrief {
  const lines = narrative.split('\n')

  // Find the first heading line to split overview from the sectioned body. No heading
  // means the whole narrative is the overview and there are no sections.
  const firstHeadingIndex = lines.findIndex((line) => SECTION_HEADING.test(line))
  if (firstHeadingIndex === -1) {
    return { overview: narrative.trim(), sections: [] }
  }

  const overview = lines.slice(0, firstHeadingIndex).join('\n').trim()

  // Walk the remaining lines, building sections/bullets immutably: each step produces a
  // new array/object rather than mutating an accumulator in place.
  let sections: BriefSection[] = []
  for (const line of lines.slice(firstHeadingIndex)) {
    const headingMatch = line.match(SECTION_HEADING)
    if (headingMatch) {
      sections = [...sections, { heading: headingMatch[1].trim(), bullets: [] }]
      continue
    }

    const bulletMatch = line.match(BULLET_LINE)
    if (bulletMatch && sections.length > 0) {
      const current = sections[sections.length - 1]
      const updated = { ...current, bullets: [...current.bullets, makeBullet(bulletMatch[1])] }
      sections = [...sections.slice(0, -1), updated]
      continue
    }

    const relatedMatch = line.match(RELATED_LINE)
    if (relatedMatch && sections.length > 0) {
      const current = sections[sections.length - 1]
      if (current.bullets.length > 0) {
        const lastBullet = current.bullets[current.bullets.length - 1]
        const updatedBullet = { ...lastBullet, related: parseCardLinks(relatedMatch[1]) }
        const updatedSection = {
          ...current,
          bullets: [...current.bullets.slice(0, -1), updatedBullet],
        }
        sections = [...sections.slice(0, -1), updatedSection]
      }
      continue
    }
    // Blank lines and anything else (e.g. stray prose) are ignored per the grammar.
  }

  return { overview, sections }
}
