// The tabs of the Profile page: their keys, their short labels, and which tab holds a given problem.
import type { Profile } from '../../api/types'
import { LIMITS, type ProfileErrors } from './validate'

export type ProfileTabKey = 'about' | 'sections' | 'topics' | 'projects' | 'avoid' | 'learned'

/** The tabs in the order the strip shows them. "Learned" is the short label of "What Spyglass has learned". */
export const PROFILE_TABS: ReadonlyArray<{ key: ProfileTabKey; label: string }> = [
  { key: 'about', label: 'About you' },
  { key: 'sections', label: 'Sections' },
  { key: 'topics', label: 'Topics' },
  { key: 'projects', label: 'Your projects' },
  { key: 'avoid', label: 'Leave out' },
  { key: 'learned', label: 'Learned' },
]

/**
 * The first tab (in strip order) that holds a validation problem, or null when there is none.
 * The page opens it after a refused save, because the problem would otherwise sit in a hidden tab.
 * A problem about a list as a whole belongs to the topics when that list is over its limit, otherwise
 * to the leave-out list.
 */
export function firstTabWithProblem(errors: ProfileErrors, profile: Profile): ProfileTabKey | null {
  if (errors.statement) return 'about'
  if (Object.keys(errors.sections).length > 0) return 'sections'
  if (Object.keys(errors.topics).length > 0 || profile.topics.length > LIMITS.topics) return 'topics'
  if (Object.keys(errors.avoid).length > 0 || errors.lists.length > 0) return 'avoid'
  return null
}
