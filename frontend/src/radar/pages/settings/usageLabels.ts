// usageLabels: plain names for what a model call was for, as the usage report names it.

const PURPOSES: Record<string, string> = {
  chat: 'Questions about an item',
  feed_chat: 'Questions about your feed',
  triage: 'Sorting new items',
  digest: 'Reading and summarising items',
  brief_opening: 'The brief’s opening',
  watch_review: 'Watch checks',
  discovery: 'Finding companies to watch',
  filing: 'Filing',
  other: 'Other writing jobs',
}

/** The words for a purpose; an unknown one is shown as it came. */
export function purposeLabel(purpose: string): string {
  return PURPOSES[purpose] ?? purpose
}
