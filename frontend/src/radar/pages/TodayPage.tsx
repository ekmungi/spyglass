// Today: the finite daily brief. Date, meta, opening, then the sections in a fixed order, each with a
// slider over its stories, then "You are caught up" and, when some items were not judged yet, a line
// saying so. j/k move, Enter opens, s saves.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getBrief, getToday } from '../api/client'
import { ApiError, errorMessage } from '../api/errors'
import type { BriefDoc, Story } from '../api/types'
import { AskPill } from '../assistant/AskPill'
import { useAskPill } from '../assistant/useAskPill'
import { focusComposer, setAssistTarget } from '../assistant/assistStore'
import { openItem } from '../components/openItem'
import { useListKeys } from '../hooks/useListKeys'
import { useResource } from '../hooks/useResource'
import { navigate } from '../router'
import { toggleSave } from '../state/itemState'
import { setReadingList } from '../state/readingList'
import { BriefSection } from '../today/BriefSection'
import { BriefSkeleton, CaughtUp, EmptyBrief } from '../today/BriefStates'
import { Masthead } from '../today/Masthead'
import { orderedSections, sectionStories } from '../today/sections'
import { Button, EmptyState } from '../ui'
import '../today/today.css'

/** Point the assistant at a day's brief and put the cursor in its composer. */
function askAboutBrief(day: string): void {
  setAssistTarget({ kind: 'brief', day })
  focusComposer('today')
}

interface BriefBodyProps {
  brief: BriefDoc
  days: string[]
  latestDay: string | null
  active: boolean
  /** Earlier days whose brief was never opened (the one on screen is left out). */
  unopenedDays: string[]
  /** One line on background filing, or null. */
  filingLine: string | null
  askRef: (element: HTMLElement | null) => void
}

/** The brief body: sections, the end marker and the line about unjudged items; owns keyboard navigation. */
function BriefBody({ brief, days, latestDay, active, unopenedDays, filingLine, askRef }: BriefBodyProps) {
  const sections = useMemo(() => orderedSections(brief), [brief])
  // Every story of the page in page order: section by section, picked before unpicked. j and k walk
  // this list (a section turns its slider to the selected story), and the reader's previous and next
  // follow it through the reading list.
  const flat: Story[] = useMemo(() => sections.flatMap((section) => sectionStories(section)), [sections])
  // Index of each section's first story in the flat list, for keyboard selection.
  const starts = useMemo(
    () => sections.map((_, index) => sections.slice(0, index).reduce((total, section) => total + sectionStories(section).length, 0)),
    [sections],
  )
  const [container, setContainer] = useState<HTMLElement | null>(null)

  const onOpen = useCallback((index: number) => flat[index] && openItem(flat[index].item_id), [flat])
  const onSave = useCallback((index: number) => flat[index] && void toggleSave(flat[index].item_id, flat[index].state), [flat])
  const [selected, setSelected] = useListKeys({ count: flat.length, enabled: active, onOpen, onSave, container })

  useEffect(() => {
    if (active) setAssistTarget({ kind: 'brief', day: brief.day })
  }, [active, brief.day])

  useEffect(() => {
    if (active) setReadingList('Today', flat.map((story) => story.item_id), 'today')
  }, [active, flat])

  return (
    <article className="r-brief" ref={setContainer}>
      <Masthead brief={brief} days={days} latestDay={latestDay} onAsk={() => askAboutBrief(brief.day)} askRef={askRef} unopenedDays={unopenedDays} filingLine={filingLine} />
      {sections.map((section, index) => (
        <BriefSection key={section.key} section={section} start={starts[index]} selected={selected} onSelect={setSelected} />
      ))}
      <CaughtUp filteredOut={brief.filtered_out} />
      {brief.degraded && brief.notice && <p className="r-meta r-brief__endnote">{brief.notice}</p>}
    </article>
  )
}

/** Route component for #/today and #/today/<day>. */
export function TodayPage({ day, active = true }: { day?: string; active?: boolean }) {
  // Entering Today (or coming back from the reader, or returning to the window after a while)
  // fetches a fresh copy; a cached answer is shown meanwhile and replaced only if it differs.
  const today = useResource('today', getToday, { active, revalidateOnFocus: true })
  const dayBrief = useResource(day ? `brief:${day}` : null, (signal) => getBrief(day as string, signal), { active })
  const latestDay = today.data?.brief?.day ?? today.data?.days?.[0] ?? null
  const viewingLatest = !day || day === latestDay
  const brief = viewingLatest ? today.data?.brief : dayBrief.data
  // While the first answer is on its way, or a cached "no brief yet" is being rechecked, show the
  // skeleton rather than flashing an empty state that may be about to disappear.
  const loading = viewingLatest ? today.loading || (!brief && today.refreshing) : dayBrief.loading
  const error = viewingLatest ? today.error : dayBrief.error
  const days = today.data?.days ?? []

  const onComposed = (composed: BriefDoc) => {
    today.setData((current) => ({
      brief: composed,
      days: current?.days?.includes(composed.day) ? current.days : [composed.day, ...(current?.days ?? [])],
      status: current?.status ?? {},
    }))
  }

  const ask = useAskPill('today', active)
  const unopenedDays = (today.data?.unopened_days ?? []).filter((unopened) => unopened !== brief?.day)
  const filingLine = today.data?.filing?.line ?? null

  let body
  // Keyed by day, so another day's brief starts with no story selected and every section on its
  // first page, even when it was cached and draws at once.
  if (brief) body = <BriefBody key={brief.day} brief={brief} days={days} latestDay={latestDay} active={active} unopenedDays={unopenedDays} filingLine={filingLine} askRef={ask.watchButton} />
  else if (loading) body = <BriefSkeleton />
  else if (error && !(error instanceof ApiError && error.status === 404)) {
    body = (
      <EmptyState
        title="The brief could not be loaded"
        body={errorMessage(error)}
        action={
          <Button variant="primary" onClick={viewingLatest ? today.reload : dayBrief.reload}>
            Try again
          </Button>
        }
      />
    )
  } else if (!viewingLatest) {
    body = (
      <EmptyState
        title="No brief for that day"
        body="Spyglass did not compose a brief on that day."
        action={<Button onClick={() => navigate({ name: 'today' })}>Go to the latest brief</Button>}
      />
    )
  } else body = <EmptyBrief onComposed={onComposed} />

  return (
    <>
      {brief && <AskPill label="Ask about today" shown={ask.shown} onClick={() => askAboutBrief(brief.day)} />}
      <div className="r-page r-page--brief">{body}</div>
    </>
  )
}
