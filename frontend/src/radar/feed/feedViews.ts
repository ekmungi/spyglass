// feedViews: the Feed's views (Everything, Missed, Saved, From you, To file) are exclusive choices
// that live in the address as one parameter each. These helpers read which view an address shows and
// build the address parameters for a chosen view.

export type FeedView = 'everything' | 'missed' | 'saved' | 'from_you' | 'to_file'

/** The views that have a parameter, in the order a link with more than one is read: the first wins. */
const VIEW_PARAMS: ReadonlyArray<{ view: Exclude<FeedView, 'everything'>; key: string; value: string }> = [
  { view: 'missed', key: 'missed', value: 'true' },
  { view: 'saved', key: 'saved', value: 'true' },
  { view: 'from_you', key: 'from_user', value: 'true' },
  { view: 'to_file', key: 'filing', value: 'waiting' },
]

/**
 * The view an address shows. When an old link carries several view parameters, the first in the order
 * Missed, Saved, From you, To file is the one shown. `filingOn` is whether filing is set up; without it
 * the To file parameter is ignored, as the query ignores it.
 */
export function currentView(params: Record<string, string>, filingOn: boolean): FeedView {
  const found = VIEW_PARAMS.find((entry) => params[entry.key] === entry.value && (entry.view !== 'to_file' || filingOn))
  return found ? found.view : 'everything'
}

/** The address parameters after choosing `view`: every view parameter dropped, then the chosen one set. Other filters stay. */
export function paramsForView(params: Record<string, string>, view: FeedView): Record<string, string> {
  const next = { ...params }
  for (const entry of VIEW_PARAMS) delete next[entry.key]
  const chosen = VIEW_PARAMS.find((entry) => entry.view === view)
  if (chosen) next[chosen.key] = chosen.value
  return next
}
