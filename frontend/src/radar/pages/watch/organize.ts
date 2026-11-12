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

/** Every category name in use, for the category suggestions in the add and edit dialog. */
export function categoryNames(register: WatchRegister): string[] {
  return register.categories.map((category) => category.name).filter((name) => name && name !== 'Other')
}
