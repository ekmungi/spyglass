// The Watch page's only door to the server: the shared client for the plain calls, plus the
// calls that carry the news search query and the discovery counts.
import { request } from '../../api/client'
import type { WatchDiscoverResponse, WatchEntity, WatchKind, WatchResponse, WatchStatus } from '../../api/types'

export {
  getWatch,
  deleteWatch,
  getTracks,
  createTrack,
  patchTrack,
  deleteTrack,
  patchWatchGroup,
  restoreWatchGroup,
  reviewWatch,
  applyWatchReview,
} from '../../api/client'

/** A register entry as the server sends it (the shared shape includes the news search query). */
export type WatchEntry = WatchEntity

/** The register as the page uses it. */
export type WatchRegister = WatchResponse

/** The discovery reply: new suggestions plus how many proposed names were dropped or already known. */
export type DiscoverResult = WatchDiscoverResponse

export interface EntryFields {
  name: string
  kind: WatchKind | string
  category: string
  query: string | null
}

/** Ask the model for organisations for a topic; the call can take a minute. */
export const discoverTopic = (topic: string) => request<DiscoverResult>('POST', '/watch/discover', { topic })

/** Follow a new entity; it is active at once. */
export const addEntry = (fields: EntryFields) =>
  request<WatchEntry>('POST', '/watch', {
    name: fields.name,
    kind: fields.kind,
    category: fields.category,
    ...(fields.query ? { query: fields.query } : {}),
  })

/** Change some fields of one entity (including accepting or muting it through `status`). */
export const changeEntry = (id: number, changes: Partial<EntryFields> & { status?: WatchStatus }) =>
  request<WatchEntry>('PATCH', `/watch/${id}`, changes)
