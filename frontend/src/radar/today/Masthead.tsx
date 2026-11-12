// Masthead: the date as the title, one line of meta, the day switcher, "Ask about today", and
// the brief's opening sentences.
import type { BriefDoc } from '../api/types'
import { formatDayShort, formatDayTitle } from '../lib/format'
import { navigate } from '../router'
import { briefMeta } from './briefMeta'
import { FilingLine } from './FilingLine'
import { UnopenedLine } from './UnopenedLine'
import { Button, IconAsk, IconExpand, Menu } from '../ui'
import type { Ref } from 'react'

export interface MastheadProps {
  brief: BriefDoc
  days: string[]
  latestDay: string | null
  onAsk: () => void
  /** Attached to the Ask button so the page can tell when it has scrolled out of view. */
  askRef?: Ref<HTMLButtonElement>
  /** Days of the last week whose brief was never opened. */
  unopenedDays?: string[]
  /** One line on background filing ("Filed yesterday: 9 items. 2 questions are open."), or null. */
  filingLine?: string | null
}

/** The top of Today. */
export function Masthead({ brief, days, latestDay, onAsk, askRef, unopenedDays = [], filingLine = null }: MastheadProps) {
  const isLatest = latestDay === null || brief.day === latestDay
  const dayItems = days.map((day) => ({
    id: day,
    label: day === latestDay ? `${formatDayShort(day)} (latest)` : formatDayShort(day),
    checked: day === brief.day,
    onSelect: () => navigate(day === latestDay ? { name: 'today' } : { name: 'today', day }),
  }))
  return (
    <header className="r-masthead">
      <h1 className="r-masthead__date">{formatDayTitle(brief.day)}</h1>
      <div className="r-masthead__bar">
        <p className="r-masthead__meta">{briefMeta(brief)}</p>
        <div className="r-masthead__actions">
          {days.length > 1 && (
            <Menu
              label="Briefs by day"
              items={dayItems}
              trigger={
                <Button variant="quiet" size="sm">
                  Earlier briefs <IconExpand size={14} />
                </Button>
              }
            />
          )}
          <Button ref={askRef} variant="secondary" size="sm" icon={<IconAsk size={14} />} onClick={onAsk}>
            Ask about today
          </Button>
        </div>
      </div>
      <UnopenedLine days={unopenedDays} />
      <FilingLine text={filingLine} />
      {!isLatest && (
        <p className="r-masthead__past">
          An earlier brief.{' '}
          <a
            href="#/today"
            onClick={(event) => {
              event.preventDefault()
              navigate({ name: 'today' })
            }}
          >
            Go to the latest
          </a>
        </p>
      )}
      {brief.opening && <p className="r-masthead__opening">{brief.opening}</p>}
      {brief.degraded && brief.notice && <p className="r-masthead__notice">{brief.notice}</p>}
    </header>
  )
}
