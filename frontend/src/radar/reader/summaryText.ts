// summaryText: decides whether a line in the summary block only repeats the opening of the document
// below it (a paper's abstract is the usual case), so the abstract is not shown twice in a row.

/** Lower-case letters and digits only, single-spaced, so markup and punctuation cannot hide a repeat. */
function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/&[a-z#0-9]+;/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

/** How much of the document's opening is compared (characters of normalised text). */
const OPENING_LENGTH = 3000
/** Shorter lines are never treated as repeats: a short phrase can occur in any text by chance. */
const MIN_LENGTH = 60
/** How much of the line must be found at the document's opening. */
const MATCH_LENGTH = 80

/** True when `text` (at least a sentence long) appears in the first part of the document `html`. */
export function repeatsDocumentStart(text: string, html: string | null | undefined): boolean {
  if (!html) return false
  const line = normalise(text)
  if (line.length < MIN_LENGTH) return false
  const opening = normalise(html.replace(/<[^>]*>/g, ' ')).slice(0, OPENING_LENGTH)
  return opening.includes(line.slice(0, MATCH_LENGTH))
}
