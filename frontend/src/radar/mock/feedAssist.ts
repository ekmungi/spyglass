// Sample-mode answers for the assistant conversation about the whole feed and for the "related"
// endpoints: items are matched to a text by shared words, and answers cite them as [#id].
import type { RadarItem, RelatedItem, RetrievedItem, SendMessageBody, Thread } from '../api/types'
import { mockState } from './store'

const STOP = new Set(['what', 'which', 'with', 'have', 'about', 'from', 'that', 'this', 'the', 'and', 'for', 'are', 'any', 'does', 'show', 'find', 'feed', 'my', 'me', 'is', 'in', 'of', 'on', 'to', 'a', 'an'])

/** Items cited per turn in a sample answer at most. */
const CITED = 4

/** The thread's remembered retrieved items, newest turn last (the real service keeps the same list). */
const remembered = new Map<number, RetrievedItem[]>()

/** Forget every remembered set (a fresh sample session, tests). */
export function resetFeedMock(): void {
  remembered.clear()
}

/** The words of a text worth matching on. */
function words(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9][a-z0-9-]{2,}/g) ?? []).filter((word) => !STOP.has(word))
}

/** How many of `query`'s words an item mentions, as a share of the words asked for. */
function overlap(item: RadarItem, query: string[]): number {
  if (!query.length) return 0
  const haystack = `${item.headline} ${item.title} ${item.why ?? ''} ${item.origin} ${item.entities.join(' ')} ${item.key_points.join(' ')}`.toLowerCase()
  return query.filter((word) => haystack.includes(word)).length / query.length
}

/** True for the conversation about the feed (a thread with neither an item nor a day). */
export function isFeedThread(thread: Thread | undefined): boolean {
  return Boolean(thread) && thread?.item_id === null && thread?.brief_day === null
}

/** Sample items close to a text, best first, each with a match between 0.5 and 0.98. */
export function relatedToText(text: string, limit = 40): RelatedItem[] {
  const query = words(text)
  return mockState()
    .items.filter((item) => item.tier !== 'out')
    .map((item) => ({ item, share: overlap(item, query) }))
    .filter((entry) => entry.share > 0)
    .sort((a, b) => b.share - a.share || (b.item.score ?? 0) - (a.item.score ?? 0))
    .slice(0, limit)
    .map(({ item, share }) => ({ ...item, match: Math.round((0.5 + 0.48 * share) * 100) / 100 }))
}

/** Sample items close to another item: the same section first, then shared names. */
export function relatedToItem(id: number, limit = 40): RelatedItem[] {
  const own = mockState().items.find((item) => item.id === id)
  if (!own) return []
  return mockState()
    .items.filter((item) => item.id !== id && item.tier !== 'out')
    .map((item) => ({ item, share: (item.section === own.section ? 0.5 : 0) + (item.entities.some((name) => own.entities.includes(name)) ? 0.4 : 0) + (item.kind === own.kind ? 0.08 : 0) }))
    .filter((entry) => entry.share >= 0.5)
    .sort((a, b) => b.share - a.share || (b.item.score ?? 0) - (a.item.score ?? 0))
    .slice(0, limit)
    .map(({ item, share }) => ({ ...item, match: Math.min(0.98, Math.round((0.45 + share * 0.5) * 100) / 100) }))
}

/** The items with these ids, in the order asked; unknown ids are left out. */
export function itemsByIds(ids: number[]): RadarItem[] {
  const all = mockState().items
  return ids.flatMap((id) => all.filter((item) => item.id === id))
}

/** The strongest recent sample items (the "this week" presets). */
function strongest(limit: number): RadarItem[] {
  return [...mockState().items]
    .filter((item) => item.tier === 'top' || item.tier === 'notable')
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .slice(0, limit)
}

const cite = (item: RadarItem) => `[#${item.id}]`

/** One sample answer about the feed, with the items it was built from. */
export function feedTurn(body: Pick<SendMessageBody, 'content' | 'action'>): { text: string; retrieved: RetrievedItem[] } {
  const picked = body.action === 'feed_week' || body.action === 'feed_themes' ? strongest(8) : relatedToText(`${body.content}`, 12)
  const shown = picked.slice(0, CITED)
  const retrieved = picked.map((item) => ({ id: item.id, headline: item.headline }))
  if (!shown.length) return { text: 'Nothing in your feed is close to that question, so there is nothing to cite. Try different words, or use Related in the Feed to browse by topic.', retrieved: [] }
  if (body.action === 'feed_themes') {
    const bySection = new Map<string, RadarItem[]>()
    for (const item of picked) bySection.set(item.section_label || 'Other', [...(bySection.get(item.section_label || 'Other') ?? []), item])
    const lines = [...bySection.entries()].slice(0, 3).map(([label, group]) => `**${label}.** ${group.slice(0, 2).map((item) => `${item.headline} ${cite(item)}`).join('; ')}.`)
    return { text: `Three themes run through the week:\n\n${lines.join('\n\n')}`, retrieved }
  }
  if (body.action === 'feed_week') {
    const lines = shown.map((item, index) => `${index + 1}. **${item.headline}** ${cite(item)}. ${item.why ?? 'Worth a look.'}`)
    return { text: `The items that matter most this week:\n\n${lines.join('\n')}`, retrieved }
  }
  const lines = shown.map((item) => `- ${item.headline} ${cite(item)}`)
  return { text: `Your feed has ${picked.length} close ${picked.length === 1 ? 'item' : 'items'}. The nearest ${shown.length === 1 ? 'is' : 'are'}:\n\n${lines.join('\n')}\n\nUse "Show these in the Feed" below to see them as a list.`, retrieved }
}

/** Remember what a feed turn retrieved, and return everything the thread has retrieved so far. */
export function rememberRetrieved(threadId: number, added: RetrievedItem[]): RetrievedItem[] {
  const ids = new Set(added.map((entry) => entry.id))
  const merged = [...(remembered.get(threadId) ?? []).filter((entry) => !ids.has(entry.id)), ...added]
  remembered.set(threadId, merged)
  return merged
}

/** What a feed thread has retrieved so far. */
export function retrievedOf(threadId: number): RetrievedItem[] {
  return remembered.get(threadId) ?? []
}
