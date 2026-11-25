// VoteButtons: the thumbs up and thumbs down for "More like this" and "Less like this", on a row and
// in the reader bar. A pressed thumb stays lit; pressing it again takes the vote back.
import type { MouseEvent } from 'react'
import type { ItemState, Vote } from '../api/types'
import { setVote, useItemState } from '../state/itemState'
import { IconButton, IconLessLikeThis, IconMoreLikeThis } from '../ui'

export interface VoteButtonsProps {
  itemId: number
  /** The vote the caller shows; a vote the reader just cast here takes over at once. */
  vote: 'more' | 'less' | null
  /** Show the pair at all times (the reader bar). Otherwise only a pointed-at or focused row, or a set vote, shows it. */
  always?: boolean
  /** Open the tooltips below the buttons, for a bar at the top of the window. */
  tipBelow?: boolean
}

/**
 * The item state that `setVote` and `useItemState` are given. Both read only `vote` from it and only
 * ever change the vote, so the other fields are neutral placeholders that are never shown or sent.
 */
function stateWithVote(vote: Vote): ItemState {
  return { saved: false, opened: false, vote, from_user: false, captured_via: null, vault_path: null }
}

/** The two thumbs, each a toggle (aria-pressed) that records the vote through the shared item state. */
export function VoteButtons({ itemId, vote, always = false, tipBelow = false }: VoteButtonsProps) {
  const base = stateWithVote(vote)
  const shown = useItemState(itemId, base).vote
  const side = tipBelow ? 'bottom' : 'top'
  const cast = (choice: 'more' | 'less') => (event: MouseEvent) => {
    // The thumbs sit inside a row whose link opens the item; a vote must not open it.
    event.stopPropagation()
    void setVote(itemId, base, choice)
  }
  const classes = ['r-votes', always ? 'r-votes--always' : '', shown ? 'is-voted' : ''].filter(Boolean).join(' ')
  return (
    <span className={classes}>
      <IconButton
        size="sm"
        tooltipSide={side}
        label="More like this"
        pressed={shown === 'more'}
        icon={<IconMoreLikeThis size={16} />}
        onClick={cast('more')}
      />
      <IconButton
        size="sm"
        tooltipSide={side}
        label="Less like this"
        pressed={shown === 'less'}
        icon={<IconLessLikeThis size={16} />}
        onClick={cast('less')}
      />
    </span>
  )
}
