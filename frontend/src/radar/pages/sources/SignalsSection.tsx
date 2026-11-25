// SignalsSection: the automatic searches (news topics, Hacker News, community papers, the watch
// sweep), each with its name and whether it is healthy; the time of its last run and what it found
// are behind the row's Details button.
import { useId, useState } from 'react'
import { SectionHeading } from '../../ui'
import type { CollectorRow } from './api'
import { collectorStatus, newItemsText } from './describe'
import { DetailsButton } from './DetailsButton'
import { formatWhen } from './format'
import { signalRows } from './signalRows'

/** Plain names for collectors whose server label may be missing. */
const FALLBACK_LABEL: Record<string, string> = {
  news: 'News search',
  hn: 'Hacker News',
  hf_papers: 'Community papers',
  watch: 'Watch list sweep',
}

export interface SignalsSectionProps {
  collectors: readonly CollectorRow[]
}

/** The "Searches and signals" group; renders nothing when the server reports none. */
export function SignalsSection({ collectors }: SignalsSectionProps) {
  const rows = signalRows(collectors)
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="sources-signals" className="rs-section">
      <SectionHeading id="sources-signals">Searches and signals</SectionHeading>
      <ul className="r-rows">
        {rows.map((row) => (
          <SignalRow key={row.key} row={row} />
        ))}
      </ul>
    </section>
  )
}

function SignalRow({ row }: { row: CollectorRow }) {
  const [open, setOpen] = useState(false)
  const nameId = useId()
  const status = collectorStatus(row)
  const found = row.status === 'ok' ? newItemsText(row.newItems) : ''
  const last = row.lastRun ? `Last run ${formatWhen(row.lastRun)}` : ''
  const details = [last, found].filter(Boolean).join(' · ')
  return (
    <li className="rs-row">
      <div className="rs-main">
        <div className="rs-line">
          <span className="rs-name" id={nameId}>
            {row.label !== row.key ? row.label : (FALLBACK_LABEL[row.key] ?? row.label)}
          </span>
          <span className={status.tone === 'problem' ? 'rs-problem' : status.tone === 'ok' ? 'rs-ok' : 'r-meta'}>
            {status.tone === 'problem' ? 'Failing' : status.text}
          </span>
        </div>
        {/* A failure stays in view: the reader has to act on it, so it is not part of the details. */}
        {status.tone === 'problem' && <p className="rs-problem">{status.text}</p>}
        {open && details && <p className="r-meta">{details}</p>}
      </div>
      {details && <DetailsButton open={open} onToggle={() => setOpen((shown) => !shown)} nameId={nameId} />}
    </li>
  )
}
