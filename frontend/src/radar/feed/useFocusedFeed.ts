// useFocusedFeed: the three ways the Feed can show a hand-picked list instead of the paged feed,
// each carried in the address so Back works: `cited` (the items an assistant answer cited, in the
// order cited), `related_item` (items close to one item) and `related` (items close to typed text).
import { getFeedItems, getRelated } from '../api/client'
import { errorMessage } from '../api/errors'
import type { RadarItem } from '../api/types'
import { useResource } from '../hooks/useResource'

export type FocusMode = 'cited' | 'related_item' | 'related'

/** The most item ids an address can carry (the service answers for 50 at a time). */
export const MAX_CITED = 50

/** The positive whole numbers of a comma list, once each, in order; anything else is dropped. */
export function parseIds(text: string | undefined): number[] {
  const ids: number[] = []
  for (const part of (text ?? '').split(',')) {
    const id = Number(part)
    if (Number.isInteger(id) && id > 0 && !ids.includes(id)) ids.push(id)
  }
  return ids.slice(0, MAX_CITED)
}

/** Which special list the address asks for (cited wins over related_item, which wins over related), or null. */
export function focusMode(params: Record<string, string>): FocusMode | null {
  if (parseIds(params.cited).length) return 'cited'
  if (parseIds(params.related_item).length) return 'related_item'
  if ((params.related ?? '').trim()) return 'related'
  return null
}

export interface FocusedFeed {
  mode: FocusMode | null
  items: RadarItem[]
  loading: boolean
  error: string | null
  /** The words for the chip above the list ("Related to: …"), without the Clear button. */
  chip: string | null
  reload: () => void
}

interface Answer {
  items: RadarItem[]
  chip: string
}

/** Load the special list for the address, if it asks for one. Paused while the page is hidden. */
export function useFocusedFeed(params: Record<string, string>, active: boolean): FocusedFeed {
  const mode = focusMode(params)
  const cited = parseIds(params.cited)
  const relatedItem = parseIds(params.related_item)[0]
  const text = (params.related ?? '').trim()
  const key = mode === 'cited' ? `focus:cited:${cited.join(',')}` : mode === 'related_item' ? `focus:item:${relatedItem}` : mode === 'related' ? `focus:text:${text}` : null
  const resource = useResource<Answer>(
    key,
    async (signal) => {
      if (mode === 'cited') return { items: (await getFeedItems(cited, signal)).items, chip: "From the assistant's answer" }
      if (mode === 'related_item') {
        const found = await getRelated({ item_id: relatedItem }, signal)
        return { items: found.items, chip: `Related to: ${found.query.headline || `item ${relatedItem}`}` }
      }
      return { items: (await getRelated({ text }, signal)).items, chip: `Related to: ${text}` }
    },
    { active },
  )
  // Until the answer arrives the chip still names what was asked for, so the list never looks unexplained.
  const waiting = mode === 'cited' ? "From the assistant's answer" : mode === 'related' ? `Related to: ${text}` : mode === 'related_item' ? 'Related to this item' : null
  return {
    mode,
    items: resource.data?.items ?? [],
    loading: mode !== null && resource.loading,
    error: mode !== null && resource.error ? errorMessage(resource.error) : null,
    chip: resource.data?.chip ?? waiting,
    reload: resource.reload,
  }
}
