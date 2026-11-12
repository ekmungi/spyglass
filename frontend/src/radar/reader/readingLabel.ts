// readingLabel: the reading-time part of the reader's meta line.
import type { ItemDetail } from '../api/types'
import { readingTimeLabel, WORDS_PER_MINUTE } from '../lib/format'

/**
 * "6 min read" for an article ("under a minute" when it is shorter); for a PDF "PDF · 212 pages" when the page count is known and nothing
 * when it is not (the text length of a thesis says nothing useful about reading time).
 */
export function readingLabel(reader: ItemDetail['reader']): string | null {
  if (!reader) return null
  if (reader.kind === 'pdf') {
    const pages = reader.page_count ?? 0
    return pages > 0 ? `PDF · ${pages} ${pages === 1 ? 'page' : 'pages'}` : null
  }
  return reader.word_count > 0 ? readingTimeLabel(reader.word_count / WORDS_PER_MINUTE) : null
}
