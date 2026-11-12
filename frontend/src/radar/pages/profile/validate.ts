// Validation for the profile form. The limits mirror the service's, so a refusal from the server
// is rare and every message names the field and what to do.
import type { Profile } from '../../api/types'

export const LIMITS = {
  statement: 2000,
  label: 200,
  description: 600,
  topicName: 200,
  topics: 100,
  avoid: 50,
} as const

export interface ProfileErrors {
  statement?: string
  sections: Record<number, { label?: string; description?: string }>
  topics: Record<number, { name?: string; section?: string }>
  avoid: Record<number, string>
  /** Problems about the list as a whole (too many entries). */
  lists: string[]
}

/** How many separate problems the errors hold. */
export function countErrors(errors: ProfileErrors): number {
  const nested = (map: Record<number, object>) => Object.values(map).reduce((sum, entry) => sum + Object.keys(entry).length, 0)
  return (errors.statement ? 1 : 0) + nested(errors.sections) + nested(errors.topics) + Object.keys(errors.avoid).length + errors.lists.length
}

/** Check a draft profile; an empty result (countErrors 0) means it can be saved. */
export function validateProfile(draft: Profile): ProfileErrors {
  const errors: ProfileErrors = { sections: {}, topics: {}, avoid: {}, lists: [] }
  const statement = draft.statement.trim()
  if (!statement) errors.statement = 'Describe who you are and what you need to know; Spyglass cannot judge without it.'
  else if (statement.length > LIMITS.statement) errors.statement = `Keep this under ${LIMITS.statement} characters (it is ${statement.length}).`

  draft.sections.forEach((section, index) => {
    const entry: { label?: string; description?: string } = {}
    if (!section.label.trim()) entry.label = 'Give this section a name.'
    else if (section.label.trim().length > LIMITS.label) entry.label = `Keep the name under ${LIMITS.label} characters.`
    if (section.description.length > LIMITS.description) entry.description = `Keep the description under ${LIMITS.description} characters.`
    if (Object.keys(entry).length) errors.sections[index] = entry
  })

  const keys = new Set(draft.sections.map((section) => section.key))
  const seenTopics = new Set<string>()
  draft.topics.forEach((topic, index) => {
    const entry: { name?: string; section?: string } = {}
    const name = topic.name.trim()
    if (!name) entry.name = 'Give this topic a name, or remove it.'
    else if (name.length > LIMITS.topicName) entry.name = `Keep the topic under ${LIMITS.topicName} characters.`
    else if (seenTopics.has(name.toLowerCase())) entry.name = 'This topic is already in the list.'
    seenTopics.add(name.toLowerCase())
    if (topic.section && !keys.has(topic.section)) entry.section = 'Pick one of the sections above, or none.'
    if (Object.keys(entry).length) errors.topics[index] = entry
  })
  if (draft.topics.length > LIMITS.topics) errors.lists.push(`You can follow at most ${LIMITS.topics} topics.`)

  const seenAvoid = new Set<string>()
  draft.avoid.forEach((text, index) => {
    const value = text.trim()
    if (!value) errors.avoid[index] = 'Write what to leave out, or remove this line.'
    else if (value.length > LIMITS.topicName) errors.avoid[index] = `Keep this under ${LIMITS.topicName} characters.`
    else if (seenAvoid.has(value.toLowerCase())) errors.avoid[index] = 'This is already in the list.'
    seenAvoid.add(value.toLowerCase())
  })
  if (draft.avoid.length > LIMITS.avoid) errors.lists.push(`You can list at most ${LIMITS.avoid} things to leave out.`)
  return errors
}

/** The draft as it should be sent: text trimmed, nothing else changed. */
export function cleanProfile(draft: Profile): Profile {
  return {
    ...draft,
    statement: draft.statement.trim(),
    sections: draft.sections.map((section) => ({ ...section, label: section.label.trim(), description: section.description.trim() })),
    topics: draft.topics.map((topic) => ({ ...topic, name: topic.name.trim() })),
    avoid: draft.avoid.map((text) => text.trim()),
  }
}

/** True when two profiles hold the same editable content (ignores trailing spaces). */
export function sameProfile(a: Profile, b: Profile): boolean {
  return JSON.stringify(cleanProfile(a)) === JSON.stringify(cleanProfile(b))
}
