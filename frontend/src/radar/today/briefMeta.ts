// briefMeta: the one meta line under the date on Today.
import type { BriefDoc } from '../api/types'
import { readingTimeLabel } from '../lib/format'

/** Count every story across the brief's sections. */
export function storyCount(brief: BriefDoc): number {
  return brief.sections.reduce((total, section) => total + section.stories.length, 0)
}

/** "6 min read · 33 stories from 212 collected" */
export function briefMeta(brief: BriefDoc): string {
  const count = storyCount(brief)
  const stories = `${count} ${count === 1 ? 'story' : 'stories'}`
  const parts = [readingTimeLabel(brief.read_minutes), brief.collected ? `${stories} from ${brief.collected} collected` : stories]
  return parts.join(' · ')
}
