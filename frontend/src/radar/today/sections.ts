// Section order, fallback headings and the stories of each section of the daily brief.
import type { BriefDoc, BriefSection, BriefSectionKey, Story } from '../api/types'

/** The order sections appear in, whatever order the document lists them. */
export const SECTION_ORDER: BriefSectionKey[] = ['top', 'watch', 'notable', 'papers', 'from_you', 'skim']

/** Headings used only when the document's own section has no title. */
export const DEFAULT_SECTION_TITLES: Record<BriefSectionKey, string> = {
  top: 'Top stories',
  watch: 'On your watch list',
  notable: 'Worth knowing',
  papers: 'Papers',
  from_you: 'From you',
  skim: 'Skim',
}

/** The heading for a section: the document's own title when present, otherwise the default. */
export function sectionTitle(section: Pick<BriefSection, 'key' | 'title'>): string {
  const own = typeof section.title === 'string' ? section.title.trim() : ''
  return own || DEFAULT_SECTION_TITLES[section.key] || ''
}

/**
 * Every story a section holds, in page order: the picked stories, then the unpicked ones (judged for
 * the section that day and left out, best first). A brief composed before unpicked stories were
 * stored has no `more`, so its sections hold their picked stories only.
 */
export function sectionStories(section: Pick<BriefSection, 'stories' | 'more'>): Story[] {
  return section.more ? [...section.stories, ...section.more] : section.stories
}

/** Sections in display order, with empty ones removed. */
export function orderedSections(brief: BriefDoc): BriefSection[] {
  const rank = (key: string) => {
    const index = SECTION_ORDER.indexOf(key as BriefSectionKey)
    return index === -1 ? SECTION_ORDER.length : index
  }
  return [...brief.sections].filter((section) => section.stories.length > 0).sort((a, b) => rank(a.key) - rank(b.key))
}
