// TierMark: the small mark that says how Spyglass judged an item. A dot for top, a ring for
// notable, nothing for skim, and quiet words for filtered-out and not-yet-judged items.
import type { Tier } from '../api/types'

const TIER_TEXT: Record<Tier, string> = {
  top: 'Top pick',
  notable: 'Worth knowing',
  skim: 'Skim',
  out: 'Filtered out',
  unjudged: 'Not judged yet',
}

/** A quiet mark for the item's tier. */
export function TierMark({ tier }: { tier: Tier }) {
  if (!TIER_TEXT[tier]) return null // a tier name this version does not know: show nothing
  if (tier === 'out' || tier === 'unjudged') return <span className="r-tier r-tier--text">{TIER_TEXT[tier]}</span>
  return (
    <span className={`r-tier r-tier--${tier}`} title={TIER_TEXT[tier]}>
      <span className="r-sr-only">{TIER_TEXT[tier]}</span>
    </span>
  )
}
