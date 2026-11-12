// readerFailure: turns the technical reason a page could not be read ("failed at T0 (HTTP 401): HTTP 401")
// into one plain sentence, keeping the original text for a Details disclosure.

export interface ReaderFailure {
  /** The sentence shown to the reader. */
  message: string
  /** The raw reason, shown only under "Details". */
  detail: string
}

/** Describe a reader failure in plain words from the service's reason text. */
export function describeReaderFailure(reason: string): ReaderFailure {
  const detail = reason.trim()
  const status = /\b(?:HTTP\s*)?([45]\d{2})\b/i.exec(detail)?.[1]
  if (status === '401' || status === '403') return { message: 'The site asked for a sign-in.', detail }
  if (status === '404' || status === '410') return { message: 'The page was not found.', detail }
  if (/time(?:d)?[\s-]?out|did not respond|no response/i.test(detail) || status === '408' || status === '504') {
    return { message: 'The site did not answer.', detail }
  }
  if (status && status.startsWith('5')) return { message: 'The site had a problem and could not show the page.', detail }
  return { message: 'Spyglass could not read the page.', detail }
}
