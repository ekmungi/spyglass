// Text helpers for displaying feed content.

const ENTITIES: Record<string, string> = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&nbsp;': ' ',
}

/** Strip HTML tags and decode common entities, collapsing whitespace.
 *  RSS summaries often embed markup; cards should show clean plain text. */
export function stripHtml(input: string): string {
  const withoutTags = input.replace(/<[^>]*>/g, ' ')
  const decoded = withoutTags.replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (m) => ENTITIES[m] ?? m)
  return decoded.replace(/\s+/g, ' ').trim()
}
