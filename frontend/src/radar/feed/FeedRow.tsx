// FeedRow: one feed item. Headline, a one-line "what" (what the page reports) or, for an item that has
// none, its "why" (only when there is one), then publication, time, section and a small tier mark.
// The headline opens the reader; the thumbs and save appear on hover.
import { memo } from 'react'
import type { RadarItem } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { SaveButton } from '../components/SaveButton'
import { VoteButtons } from '../components/VoteButtons'
import { relativeTime, sentByYou } from '../lib/format'
import { plainText } from '../lib/plainText'
import { useFilingConfigured } from '../state/filingConfigured'
import { useFiling } from '../state/filingState'
import { useItemState } from '../state/itemState'
import { TierMark } from './TierMark'

/**
 * One row of the feed. Memoised: moving the selection with j and k changes `selected` on two rows only,
 * and a long list should not redraw every row (each now holds the thumbs and their tooltips) on each press.
 */
export const FeedRow = memo(function FeedRow({ item, index, selected, onOpen }: { item: RadarItem; index: number; selected: boolean; onOpen?: () => void }) {
  const state = useItemState(item.id, item.state)
  // "Waiting to be filed" is shown only where filing is set up.
  const filingOn = useFilingConfigured()
  const waiting = useFiling(item.id, item.filing) === 'waiting' && filingOn
  const classes = ['r-feedrow', state.opened ? 'is-read' : '', selected ? 'is-selected' : '', item.tier === 'out' ? 'is-out' : ''].filter(Boolean).join(' ')
  const meta = [item.origin, relativeTime(item.published_at ?? item.fetched_at), item.section_label, state.from_user ? sentByYou(state.captured_via) : null, waiting ? 'Waiting to be filed' : null].filter(Boolean)
  // The "what" is the plain statement of what the page reports; items judged before it existed, and items
  // that were only triaged, fall back to the "why", or to no line at all.
  const line = plainText(item.what) || plainText(item.why)
  return (
    <li className={classes} data-row-index={index}>
      <div className="r-feedrow__main">
        <ItemLink id={item.id} className="r-feedrow__link" onOpen={onOpen}>
          <span className="r-feedrow__headline">{plainText(item.headline) || plainText(item.title) || item.url}</span>
        </ItemLink>
        {line && <p className="r-feedrow__why">{line}</p>}
        <p className="r-feedrow__meta">
          <TierMark tier={item.tier} />
          {meta.length > 0 && <span>{meta.join(' · ')}</span>}
        </p>
      </div>
      <VoteButtons itemId={item.id} vote={item.state.vote} />
      <SaveButton id={item.id} base={item.state} />
    </li>
  )
})
