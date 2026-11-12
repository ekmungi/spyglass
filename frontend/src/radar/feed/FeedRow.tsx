// FeedRow: one feed item. Headline, a one-line why (only when there is one), then publication,
// time, section and a small tier mark. The headline opens the reader; save appears on hover.
import type { RadarItem } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { SaveButton } from '../components/SaveButton'
import { relativeTime, sentByYou } from '../lib/format'
import { plainText } from '../lib/plainText'
import { useFilingConfigured } from '../state/filingConfigured'
import { useFiling } from '../state/filingState'
import { useItemState } from '../state/itemState'
import { TierMark } from './TierMark'

/** One row of the feed. */
export function FeedRow({ item, index, selected }: { item: RadarItem; index: number; selected: boolean }) {
  const state = useItemState(item.id, item.state)
  // "Waiting to be filed" is shown only where filing is set up.
  const filingOn = useFilingConfigured()
  const waiting = useFiling(item.id, item.filing) === 'waiting' && filingOn
  const classes = ['r-feedrow', state.opened ? 'is-read' : '', selected ? 'is-selected' : '', item.tier === 'out' ? 'is-out' : ''].filter(Boolean).join(' ')
  const meta = [item.origin, relativeTime(item.published_at ?? item.fetched_at), item.section_label, state.from_user ? sentByYou(state.captured_via) : null, waiting ? 'Waiting to be filed' : null].filter(Boolean)
  // Items that were only triaged have no "why"; leave no empty line for them.
  const why = plainText(item.why)
  return (
    <li className={classes} data-row-index={index}>
      <div className="r-feedrow__main">
        <ItemLink id={item.id} className="r-feedrow__link">
          <span className="r-feedrow__headline">{plainText(item.headline) || plainText(item.title) || item.url}</span>
        </ItemLink>
        {why && <p className="r-feedrow__why">{why}</p>}
        <p className="r-feedrow__meta">
          <TierMark tier={item.tier} />
          {meta.length > 0 && <span>{meta.join(' · ')}</span>}
        </p>
      </div>
      <SaveButton id={item.id} base={item.state} />
    </li>
  )
}
