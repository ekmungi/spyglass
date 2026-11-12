// The How to content in reading order, plus lookup and search helpers for the page.
import { ASKING_GROUP, KEEPING_GROUP, SENDING_GROUP } from './tasksWork'
import { READING_GROUP, SETTINGS_GROUP, TUNING_GROUP } from './tasksReading'
import { PAPERS_GROUP, SOURCES_GROUP, WATCH_GROUP } from './tasksSources'
import type { HelpGroup, HelpTask } from './types'

/** Every group, in the order the page shows them. */
export const HELP_GROUPS: HelpGroup[] = [READING_GROUP, ASKING_GROUP, SOURCES_GROUP, WATCH_GROUP, PAPERS_GROUP, SENDING_GROUP, KEEPING_GROUP, TUNING_GROUP, SETTINGS_GROUP]

/** Whether this Spyglass can offer the task: a task that needs filing is offered only where filing is set up. */
export function isAvailable(task: HelpTask, filingOn: boolean): boolean {
  return task.needs !== 'filing' || filingOn
}

/** Every task, flattened. */
export const HELP_TASKS: HelpTask[] = HELP_GROUPS.flatMap((group) => group.tasks)

/** The task with this id, or undefined. */
export function findTask(id: string | undefined): HelpTask | undefined {
  return id === undefined ? undefined : HELP_TASKS.find((task) => task.id === id)
}

/** The text a search looks in: title, purpose, steps, mechanism and keywords, lowercase, without {{ }} marks. */
function haystack(task: HelpTask): string {
  return [task.title, task.purpose, ...task.steps, task.next, ...(task.keywords ?? [])].join(' ').replace(/\{\{|\}\}/g, '').toLowerCase()
}

/**
 * Groups reduced to the tasks this Spyglass can offer that contain every word of the query; empty
 * groups are dropped. Tasks that need filing are left out unless `filingOn`.
 */
export function filterGroups(query: string, filingOn = false): HelpGroup[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  return HELP_GROUPS.map((group) => ({ ...group, tasks: group.tasks.filter((task) => isAvailable(task, filingOn) && words.every((word) => haystack(task).includes(word))) })).filter((group) => group.tasks.length > 0)
}

/** Split a step into plain and marked ({{Name}}) pieces for rendering. */
export function splitStep(step: string): { text: string; ui: boolean }[] {
  return step
    .split(/(\{\{[^}]+\}\})/)
    .filter(Boolean)
    .map((part) => (part.startsWith('{{') ? { text: part.slice(2, -2), ui: true } : { text: part, ui: false }))
}
