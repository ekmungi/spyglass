// The Find papers page's only door to the server: the search, the capture call, and the topic
// names from the profile that become example chips.
import { request } from '../../api/client'

export { searchPapers, captureLink } from '../../api/client'

/** Names of the reader's profile topics. Accepts the profile bare or wrapped as {profile: {...}}. */
export async function loadProfileTopics(signal?: AbortSignal): Promise<string[]> {
  const raw = await request<unknown>('GET', '/profile', undefined, signal)
  const doc = raw && typeof raw === 'object' && 'profile' in raw ? (raw as { profile: unknown }).profile : raw
  const topics = doc && typeof doc === 'object' ? (doc as { topics?: unknown }).topics : null
  if (!Array.isArray(topics)) return []
  return topics
    .map((topic) => (topic && typeof topic === 'object' ? (topic as { name?: unknown }).name : null))
    .filter((name): name is string => typeof name === 'string' && name.trim().length > 0)
}
