// The Watch page's layout, decided once per load: which names show in which group, the Paused list
// and the suggestion rows; plus the in-place change of one name's look, the register with names moved
// to the list their status puts them in, and the steps a group moves.
import type { WatchStatus } from '../../api/types'
import type { WatchEntry, WatchRegister } from './api'

/** A followed group as laid out at load: only the names that were active then, in the server's order. */
export interface LayoutGroup {
  name: string
  entities: WatchEntry[]
  /** Items the group brought into the Feed in the last 7 days; null when the server did not say. */
  weekCount: number | null
}

/** A muted name with the group it belongs to. */
export interface PausedName {
  entity: WatchEntry
  group: string
}

/** One row of suggestions: a profile section, or one topic search. */
export interface SuggestionRow {
  /** A section key, `topic:<topic>` for a topic search, or "" for the row of names matching no section. */
  key: string
  label: string
  /** True for a topic-search row. */
  topic: boolean
  entities: WatchEntry[]
}

export interface WatchLayout {
  groups: LayoutGroup[]
  paused: PausedName[]
  rows: SuggestionRow[]
  rejected: WatchEntry[]
}

/** Most-named first, then alphabetical, so a row reads the same on every load. */
const byCountThenName = (a: WatchEntry, b: WatchEntry) => b.count - a.count || a.name.localeCompare(b.name)

/**
 * Lay the register out once per load; the page afterwards changes only a chip's look on a click, so
 * nothing moves while it is open. Groups keep the server's order and hold the names that are active
 * now (a group with none is not shown); muted names go to `paused` with their group's name. Suggestion
 * rows are one per profile section in profile order (every section is listed, empty or not), then
 * one per topic search, then a row for names that match no profile section if there are any.
 */
export function layoutRegister(register: WatchRegister): WatchLayout {
  const groups: LayoutGroup[] = []
  const paused: PausedName[] = []
  for (const category of register.categories) {
    const active = category.entities.filter((entity) => entity.status === 'active')
    for (const entity of category.entities) if (entity.status === 'muted') paused.push({ entity, group: category.name })
    if (active.length > 0) groups.push({ name: category.name, entities: active, weekCount: category.week_count ?? null })
  }

  const searched = register.suggested.filter((entity) => entity.topic)
  const profiled = register.suggested.filter((entity) => !entity.topic)
  const known = new Set(register.sections.map((section) => section.key))
  const rows: SuggestionRow[] = register.sections.map((section) => ({
    key: section.key,
    label: section.label,
    topic: false,
    entities: profiled.filter((entity) => entity.section === section.key).sort(byCountThenName),
  }))
  const topics = Array.from(new Set(searched.map((entity) => entity.topic as string))).sort((a, b) => a.localeCompare(b))
  for (const topic of topics) {
    rows.push({ key: `topic:${topic}`, label: topic, topic: true, entities: searched.filter((entity) => entity.topic === topic) })
  }
  const stray = profiled.filter((entity) => !known.has(entity.section)).sort(byCountThenName)
  if (stray.length > 0) rows.push({ key: '', label: 'Other', topic: false, entities: stray })

  return { groups, paused, rows, rejected: register.rejected }
}

/** Name ids mapped to a status. */
export type StatusById = ReadonlyMap<number, WatchStatus>

/** The entity with the status `statuses` gives its id, or the entity itself when it gives none. */
function patched(entity: WatchEntry, statuses: StatusById): WatchEntry {
  const status = statuses.get(entity.id)
  return status === undefined || status === entity.status ? entity : { ...entity, status }
}

/**
 * The same layout with the given names' statuses changed wherever the names are shown. Nothing is
 * added, removed or reordered, so a chip keeps its place under the cursor; the layout given is not
 * changed, and it is returned as it is when there is nothing to change.
 */
export function withStatuses(layout: WatchLayout, statuses: StatusById): WatchLayout {
  if (statuses.size === 0) return layout
  const patch = (entity: WatchEntry) => patched(entity, statuses)
  return {
    groups: layout.groups.map((group) => ({ ...group, entities: group.entities.map(patch) })),
    paused: layout.paused.map((name) => ({ ...name, entity: patch(name.entity) })),
    rows: layout.rows.map((row) => ({ ...row, entities: row.entities.map(patch) })),
    rejected: layout.rejected.map(patch),
  }
}

/** The three lists of the register a status puts a name in. */
type Shelf = 'groups' | 'suggested' | 'rejected'

/** Where a status puts a name: watched and paused names in their group, the others in their own list. */
function shelfOf(status: WatchStatus): Shelf {
  if (status === 'suggested' || status === 'rejected') return status
  return 'groups'
}

/** The list with `entity` inserted where the server would list it: by name, ignoring case. */
function inNameOrder(list: readonly WatchEntry[], entity: WatchEntry): WatchEntry[] {
  const name = entity.name.toLowerCase()
  const at = list.findIndex((other) => other.name.toLowerCase() > name)
  return at < 0 ? [...list, entity] : [...list.slice(0, at), entity, ...list.slice(at)]
}

/** The group a name belongs to: its own, or "Other" when it has none (as the server groups it). */
export function groupOf(entity: WatchEntry): string {
  return entity.category || 'Other'
}

/** The groups with `entity` added to its own group, a new group going last. */
function intoGroup(categories: WatchRegister['categories'], entity: WatchEntry): WatchRegister['categories'] {
  const name = groupOf(entity)
  if (!categories.some((category) => category.name === name)) return [...categories, { name, entities: [entity] }]
  return categories.map((category) => (category.name === name ? { ...category, entities: inNameOrder(category.entities, entity) } : category))
}

/**
 * The register with the given names' statuses changed, in a copy. A name whose new status belongs in
 * another list moves there, in the order the server keeps: a watched suggestion joins its group, a
 * rejected one the rejected list, and a name taken back the suggestions. Names that stay in their
 * list keep their place. Used to lay out a name where the page first showed it, and to keep the
 * answer remembered for the next visit in step with a confirmed change.
 */
export function registerWithStatuses(register: WatchRegister, statuses: StatusById): WatchRegister {
  if (statuses.size === 0) return register
  const patch = (list: readonly WatchEntry[]) => list.map((entity) => patched(entity, statuses))
  const staying = (list: readonly WatchEntry[], shelf: Shelf) => patch(list).filter((entity) => shelfOf(entity.status) === shelf)
  const leaving = (list: readonly WatchEntry[], shelf: Shelf) => patch(list).filter((entity) => shelfOf(entity.status) !== shelf)

  const moving = [
    ...register.categories.flatMap((category) => leaving(category.entities, 'groups')),
    ...leaving(register.suggested, 'suggested'),
    ...leaving(register.rejected, 'rejected'),
  ]
  const kept: WatchRegister = {
    ...register,
    categories: register.categories.map((category) => ({ ...category, entities: staying(category.entities, 'groups') })),
    suggested: staying(register.suggested, 'suggested'),
    rejected: staying(register.rejected, 'rejected'),
  }
  return moving.reduce<WatchRegister>((next, entity) => {
    const shelf = shelfOf(entity.status)
    if (shelf === 'groups') return { ...next, categories: intoGroup(next.categories, entity) }
    return { ...next, [shelf]: inNameOrder(next[shelf], entity) }
  }, kept)
}

/**
 * How many places a group must move in the stored order to pass exactly one shown group. The
 * stored order also holds groups the page hides (all their names are paused); moving one place
 * past such a group would change nothing the reader can see. 0 when no shown group lies that way.
 */
export function groupSteps(order: readonly string[], shown: readonly string[], name: string, direction: 'up' | 'down'): number {
  const from = order.indexOf(name)
  if (from < 0) return 0
  const step = direction === 'up' ? -1 : 1
  for (let at = from + step; at >= 0 && at < order.length; at += step) {
    if (shown.includes(order[at])) return Math.abs(at - from)
  }
  return 0
}

/** Every category name in use, for the category suggestions in the add and edit dialog. */
export function categoryNames(register: WatchRegister): string[] {
  return register.categories.map((category) => category.name).filter((name) => name && name !== 'Other')
}
