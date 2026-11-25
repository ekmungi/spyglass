// The headline of an item the interface already holds, for the "Next in Today" block at the end of a
// story. The reading list keeps ids only, so the headline is read from what earlier pages loaded: an
// item opened before, Today's brief (or the day's brief the reader came from), or a Feed list.
// Nothing is fetched; when no page holds the item the block shows its position alone.
import type { BriefDoc, ItemDetail, TodayResponse } from '../api/types'
import { lookupFeedHeadline } from '../feed/useFeed'
import { peekResource } from '../hooks/useResource'
import { plainText } from '../lib/plainText'
import { readerOrigin } from '../router'

/** The headline of the story in `brief` (picked or unpicked) whose lead item is `id`, or null. */
function briefHeadline(brief: BriefDoc | null | undefined, id: number): string | null {
  for (const section of brief?.sections ?? []) {
    const story = [...section.stories, ...(section.more ?? [])].find((entry) => entry.item_id === id)
    if (story) return story.headline
  }
  return null
}

/** The headline of the brief of the day the reader was opened from, when that was an earlier day. */
function dayBriefHeadline(id: number): string | null {
  const origin = readerOrigin()
  if (origin?.name !== 'today' || !origin.day) return null
  return briefHeadline(peekResource<BriefDoc>(`brief:${origin.day}`), id)
}

/**
 * The plain-text headline of item `id` from the caches, or null. The keys are the ones the reader
 * ("item:<id>") and the Today page ("today", "brief:<day>") load their answers under.
 */
export function cachedHeadline(id: number): string | null {
  const found =
    peekResource<ItemDetail>(`item:${id}`)?.headline ||
    briefHeadline(peekResource<TodayResponse>('today')?.brief, id) ||
    dayBriefHeadline(id) ||
    lookupFeedHeadline(id)
  return found ? plainText(found) : null
}
