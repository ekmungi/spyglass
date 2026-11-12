// Author list wording for a paper row.

/** "A, B, C and 4 others" from an author list; empty when there are none. */
export function formatAuthors(authors: readonly string[], shown = 3): string {
  const clean = authors.map((name) => name.trim()).filter(Boolean)
  if (clean.length <= shown) return clean.join(', ')
  const rest = clean.length - shown
  return `${clean.slice(0, shown).join(', ')} and ${rest} ${rest === 1 ? 'other' : 'others'}`
}

