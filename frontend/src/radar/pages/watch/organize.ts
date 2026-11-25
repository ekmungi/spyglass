// The Watch page's layout, decided once per load: which names show in which group, the Paused list
// and the suggestion rows; plus the in-place change of one name's look and the steps a group moves.
import type { WatchStatus } from '../../api/types'
import { isWithinDays } from '../sources/format'
import type { WatchEntry, WatchRegister } from './api'

/** How many days a hit counts as recent for a suggestion's "Last mentioned" line. */
export const RECENT_DAYS = 7

/** True when the entity was hit within the last RECENT_DAYS days. */
export function hasRecentHit(entity: WatchEntry, now: Date = new Date()): boolean {
  return isWithinDays(entity.last_hit_at, RECENT_DAYS, now)
}

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

/**
 * The same layout with one name's status changed wherever the name is shown. Nothing is added,
 * removed or reordered, so a chip keeps its place under the cursor; the layout given is not changed.
 */
export function withStatus(layout: WatchLayout, id: number, status: WatchStatus): WatchLayout {
  const patch = (entity: WatchEntry) => (entity.id === id ? { ...entity, status } : entity)
  return {
    groups: layout.groups.map((group) => ({ ...group, entities: group.entities.map(patch) })),
    paused: layout.paused.map((name) => ({ ...name, entity: patch(name.entity) })),
    rows: layout.rows.map((row) => ({ ...row, entities: row.entities.map(patch) })),
    rejected: layout.rejected.map(patch),
  }
}

/** The register with one followed name's status changed, as the next load will send it. */
export function registerWithStatus(register: WatchRegister, id: number, status: WatchStatus): WatchRegister {
  return {
    ...register,
    categories: register.categories.map((category) => ({
      ...category,
      entities: category.entities.map((entity) => (entity.id === id ? { ...entity, status } : entity)),
    })),
  }
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
