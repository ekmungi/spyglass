// SignalsSection: the automatic searches (news topics, Hacker News, community papers, the watch
// sweep) with the time of their last run, what they found, and whether they are healthy.
import { SectionHeading } from '../../ui'
import type { CollectorRow } from './api'
import { collectorStatus, newItemsText } from './describe'
import { formatWhen } from './format'

/** Collectors shown elsewhere on the page: the feeds group covers rss, "From you" the mail and chat ones, FDA has its own group. */
const SHOWN_ELSEWHERE = new Set(['rss', 'slack', 'raindrop', 'gmail', 'newsletter', 'capture', 'fda'])

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
  const rows = collectors.filter((row) => !SHOWN_ELSEWHERE.has(row.key))
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="sources-signals" className="rs-section">
      <SectionHeading id="sources-signals">Searches and signals</SectionHeading>
      <ul className="r-rows">
        {rows.map((row) => {
          const status = collectorStatus(row)
          const found = row.status === 'ok' ? newItemsText(row.newItems) : ''
          const last = row.lastRun ? `Last run ${formatWhen(row.lastRun)}` : ''
          return (
            <li key={row.key} className="rs-row">
              <div className="rs-main">
                <div className="rs-line">
                  <span className="rs-name">{row.label !== row.key ? row.label : (FALLBACK_LABEL[row.key] ?? row.label)}</span>
                  <span className={status.tone === 'problem' ? 'rs-problem' : status.tone === 'ok' ? 'rs-ok' : 'r-meta'}>
                    {status.tone === 'problem' ? 'Failing' : status.text}
                  </span>
                </div>
                {status.tone === 'problem' && <p className="rs-problem">{status.text}</p>}
                {(last || found) && <p className="r-meta">{[last, found].filter(Boolean).join(' · ')}</p>}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
