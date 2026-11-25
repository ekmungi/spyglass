// The words of the Watch page's suggestions: what a chip says to a screen reader and on hover, and the
// toast after each decision, as the approved prototype words them.
import type { WatchStatus } from '../../api/types'
import type { WatchEntry } from './api'

/** The group a watched suggestion joins: the one the cleaning step proposed, or "Other". */
export function groupOf(entity: WatchEntry): string {
  return entity.category || 'Other'
}

/** "12 items", "1 item". */
function itemsText(count: number): string {
  return `${count} ${count === 1 ? 'item' : 'items'}`
}

/** The chip's name as a screen reader says it: with its count, and "not of interest" when struck. */
export function spokenName(entity: WatchEntry): string {
  const count = entity.count > 0 ? `, named in ${itemsText(entity.count)}` : ''
  return `${entity.name}${count}${entity.status === 'rejected' ? ', not of interest' : ''}`
}

/** What a click on the chip does now, shown on hover and keyboard focus. */
export function tipText(entity: WatchEntry): string {
  if (entity.status === 'active') return `Watched. On your next visit it is in ${groupOf(entity)}. Click to undo.`
  if (entity.status === 'rejected') return 'Not of interest. Click to take it back.'
  const why = entity.count > 0 ? `Named in ${itemsText(entity.count)} in the last 30 days. ` : ''
  return `${why}Click to watch it; it joins ${groupOf(entity)}.`
}

/** The toast after a chip in a suggestion row moves from its look `entity.status` to `to`. */
export function decidedText(entity: WatchEntry, to: WatchStatus): string {
  if (to === 'active') return `Watching ${entity.name}. It joins ${groupOf(entity)}.`
  if (to === 'rejected') return `${entity.name} will not be suggested again.`
  return entity.status === 'active' ? `No longer watching ${entity.name}.` : `${entity.name} is a suggestion again.`
}

/** The toast after "Hide the rest for good". */
export function hiddenText(count: number): string {
  return `${count} ${count === 1 ? 'name' : 'names'} will not be suggested again.`
}

/** The toast after a name is taken back from the Not of interest list. */
export function takenBackText(entity: WatchEntry): string {
  return `${entity.name} can be suggested again from the next run.`
}
