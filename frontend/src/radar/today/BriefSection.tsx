// BriefSection: one section of Today, its heading and a slider over its stories: the picked stories,
// then the best unpicked ones of the same day, one page at a time. The section owns its page, and the
// page follows the keyboard selection, so j and k can walk onto a story of a later page.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { BriefSection as Section } from '../api/types'
import { IconButton, IconNext, IconPrevious, SectionHeading, Tooltip } from '../ui'
import { sectionStories, sectionTitle } from './sections'
import { StoryRow } from './StoryRow'

/** Stories on the first page of the top section: one lead across the page, then four in two columns. */
const TOP_FIRST_PAGE = 5
/** Stories on each later page of the top section: two rows of two. */
const TOP_PAGE = 4
/** Stories on each page of every other section. */
const SECTION_PAGE = 3

/** One page of a section: the position of its first story and of the story after its last. */
interface Page {
  from: number
  to: number
}

/** The direction of the last turn of the slider, for the slide-in: 0 before any turn. */
type Step = -1 | 0 | 1

/**
 * Split a section's `total` stories into pages. A section from a brief composed before unpicked
 * stories were stored (`paged` false) keeps every story on one page, so it shows no arrows.
 */
function pagesOf(key: Section['key'], total: number, paged: boolean): Page[] {
  if (!paged) return [{ from: 0, to: total }]
  const first = key === 'top' ? TOP_FIRST_PAGE : SECTION_PAGE
  const size = key === 'top' ? TOP_PAGE : SECTION_PAGE
  const pages: Page[] = [{ from: 0, to: Math.min(first, total) }]
  for (let from = first; from < total; from += size) pages.push({ from, to: Math.min(from + size, total) })
  return pages
}

interface PagerProps {
  page: Page
  /** How many stories the slider holds (picked and unpicked). */
  total: number
  /** How many stories were judged for the section that day. */
  pool?: number
  atStart: boolean
  atEnd: boolean
  onMove: (step: 1 | -1) => void
}

/**
 * The count ("4-6 of 15", or "6 of 6" for a page that holds one story) and the two arrows beside a
 * section heading. An arrow at its end is marked disabled rather than disabled, so the keyboard focus
 * stays on it; its click then does nothing (the section ignores a turn past either end).
 */
function Pager({ page, total, pool, atStart, atEnd, onMove }: PagerProps) {
  const position = page.to - page.from === 1 ? `${page.to}` : `${page.from + 1}-${page.to}`
  const count = <span className="r-brief__count">{`${position} of ${total}`}</span>
  // The slider keeps at most a dozen unpicked stories, so when more were judged the count says so.
  const judged =
    pool !== undefined && pool > total
      ? `${pool} stories were judged for this section today. The ${total} best are here, and the Feed has the rest.`
      : null
  return (
    <span className="r-brief__pager">
      {judged ? <Tooltip label={judged}>{count}</Tooltip> : count}
      {/* The tooltip is drawn for the eye only, so screen readers get the same sentence here. */}
      {judged && <span className="r-sr-only">{judged}</span>}
      <IconButton
        size="sm"
        label="Previous stories in this section"
        icon={<IconPrevious size={16} />}
        aria-disabled={atStart || undefined}
        onClick={() => onMove(-1)}
      />
      <IconButton
        size="sm"
        label="More stories in this section"
        icon={<IconNext size={16} />}
        aria-disabled={atEnd || undefined}
        onClick={() => onMove(1)}
      />
    </span>
  )
}

export interface BriefSectionProps {
  section: Section
  /** Position of the section's first story in the page's list of every story (the keyboard's list). */
  start?: number
  /** Position of the keyboard-selected story in that list; -1 when none is selected. */
  selected?: number
  /** Select a story by its position in that list (the setter of the page's keyboard selection). */
  onSelect?: (index: number) => void
}

/** One section of the brief with its slider; the top section's first page leads with one story. */
export function BriefSection({ section, start = 0, selected = -1, onSelect }: BriefSectionProps) {
  const stories = useMemo(() => sectionStories(section), [section])
  const paged = Boolean(section.more)
  const pages = useMemo(() => pagesOf(section.key, stories.length, paged), [section.key, stories.length, paged])
  const [view, setView] = useState<{ page: number; step: Step }>({ page: 0, step: 0 })
  const [followed, setFollowed] = useState(selected)
  const [focusRow, setFocusRow] = useState<number | null>(null)
  const sectionRef = useRef<HTMLElement>(null)
  // A refreshed brief may hold fewer stories than the page the reader was on.
  const page = Math.min(view.page, pages.length - 1)

  // When j or k selects a story of this section on another page, turn to that page. The state is
  // adjusted during render, as React recommends for state that follows a prop.
  if (selected !== followed) {
    setFollowed(selected)
    const target = pages.findIndex((entry) => selected - start >= entry.from && selected - start < entry.to)
    if (target >= 0 && target !== page) {
      setView({ page: target, step: target > page ? 1 : -1 })
      setFocusRow(selected)
    }
  }

  // After such a turn the selected row is new on screen, so useListKeys could not reach it: bring it
  // into view and give its link the focus here (jsdom has no scrollIntoView, hence the optional call).
  useEffect(() => {
    if (focusRow === null) return
    const row = sectionRef.current?.querySelector<HTMLElement>(`[data-row-index="${focusRow}"]`)
    row?.scrollIntoView?.({ block: 'nearest' })
    row?.querySelector<HTMLElement>('[data-row-open]')?.focus({ preventScroll: true })
  }, [focusRow])

  /** Turn the slider one page on or back; a turn past either end does nothing. */
  const move = (step: 1 | -1) => {
    const target = page + step
    if (target < 0 || target >= pages.length) return
    setView({ page: target, step })
    setFocusRow(null)
    // A selection inside this section moves to the first story of the new page, so s and Enter act
    // on a story on screen and j and k go on from there. That page already holds the new selection,
    // so following it above does not turn again. The focus stays on the arrow.
    const local = selected - start
    if (onSelect && local >= 0 && local < stories.length) onSelect(start + pages[target].from)
  }

  const current = pages[page]
  const headingId = `brief-${section.key}`
  const lead = section.key === 'top' && page === 0
  const note =
    pages.length > 1 ? (
      <Pager page={current} total={stories.length} pool={section.pool} atStart={page === 0} atEnd={page === pages.length - 1} onMove={move} />
    ) : (
      section.note
    )

  return (
    <section ref={sectionRef} className={`r-brief__section r-brief__section--${section.key}`} aria-labelledby={headingId}>
      <SectionHeading id={headingId} note={note}>
        {sectionTitle(section)}
      </SectionHeading>
      {/* A new key per page replays the slide-in of the page's stories. */}
      <ul
        key={page}
        className={lead ? 'r-brief__list r-brief__list--lead' : 'r-brief__list'}
        data-slide={view.step === 1 ? 'next' : view.step === -1 ? 'previous' : undefined}
      >
        {stories.slice(current.from, current.to).map((story, offset) => {
          const position = current.from + offset
          return (
            <StoryRow
              key={story.id}
              story={story}
              section={section.key}
              index={start + position}
              selected={selected === start + position}
              unpicked={position >= section.stories.length}
            />
          )
        })}
      </ul>
    </section>
  )
}
