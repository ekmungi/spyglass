// Pure ordering of the Watch register: which names float to the top, and where muted names go.
import { isWithinDays, parseWhen } from '../sources/format'
import type { WatchEntry, WatchRegister } from './api'

/** How many days a hit keeps a name near the top of its category. */
export const RECENT_DAYS = 7

export interface OrganizedGroup {
  name: string
  entities: WatchEntry[]
  /** Every name in the group is muted (the group was paused, or each name was muted one by one). */
  paused: boolean
  /** Items the group brought into the Feed in the last 7 days; null when the server did not say. */
  weekCount: number | null
}

export interface OrganizedRegister {
  /** Categories, names with a hit in the last week first; a paused group keeps all its (muted) names. */
  groups: OrganizedGroup[]
  /** Names muted one by one inside a group that is still followed, kept out of the way. */
  muted: WatchEntry[]
}

/** True when the entity was hit within the last RECENT_DAYS days. */
export function hasRecentHit(entity: WatchEntry, now: Date = new Date()): boolean {
  return isWithinDays(entity.last_hit_at, RECENT_DAYS, now)
}

/** Recent hits first (newest first), then everything else in alphabetical order. */
export function orderEntities(entities: readonly WatchEntry[], now: Date = new Date()): WatchEntry[] {
  const time = (entity: WatchEntry) => parseWhen(entity.last_hit_at)?.getTime() ?? 0
  return [...entities].sort((a, b) => {
    const aRecent = hasRecentHit(a, now)
    const bRecent = hasRecentHit(b, now)
    if (aRecent !== bRecent) return aRecent ? -1 : 1
    if (aRecent && bRecent && time(a) !== time(b)) return time(b) - time(a)
    return a.name.localeCompare(b.name)
  })
}

/** Split the server's register into display groups and the muted pile. */
export function organizeRegister(register: WatchRegister, now: Date = new Date()): OrganizedRegister {
  const muted: WatchEntry[] = []
  const groups = register.categories
    .map((category): OrganizedGroup => {
      const paused = category.paused ?? (category.entities.length > 0 && category.entities.every((entity) => entity.status === 'muted'))
      const followed = paused
        ? category.entities
        : category.entities.filter((entity) => {
            if (entity.status === 'muted') {
              muted.push(entity)
              return false
            }
            return true
          })
      return { name: category.name, entities: orderEntities(followed, now), paused, weekCount: category.week_count ?? null }
    })
    .filter((group) => group.entities.length > 0)
  return { groups, muted: [...muted].sort((a, b) => a.name.localeCompare(b.name)) }
}

/** A followed group as laid out at load: only the names that were active then, in the server's order. */
export interface LayoutGroup {
  name: string
  entities: WatchEntry[]
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
    if (active.length > 0) groups.push({ name: category.name, entities: active })
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

/** Every category name in use, for the category suggestions in the add and edit dialog. */
export function categoryNames(register: WatchRegister): string[] {
  return register.categories.map((category) => category.name).filter((name) => name && name !== 'Other')
}
