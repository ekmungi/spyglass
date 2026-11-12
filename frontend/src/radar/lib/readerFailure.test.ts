// Tests for the plain-words reader failure messages.
import { describe, expect, it } from 'vitest'
import { describeReaderFailure } from './readerFailure'

describe('describeReaderFailure', () => {
  it('says a sign-in is needed for 401 and 403 and keeps the technical text as detail', () => {
    const failure = describeReaderFailure('failed at T0 (HTTP 401): HTTP 401')
    expect(failure.message).toBe('The site asked for a sign-in.')
    expect(failure.detail).toBe('failed at T0 (HTTP 401): HTTP 401')
    expect(describeReaderFailure('The site refused automated reading (HTTP 403).').message).toBe('The site asked for a sign-in.')
  })

  it('says the page was not found for 404', () => {
    expect(describeReaderFailure('HTTP 404').message).toBe('The page was not found.')
  })

  it('says the site did not answer for timeouts', () => {
    expect(describeReaderFailure('failed at T1: timed out after 20s').message).toBe('The site did not answer.')
    expect(describeReaderFailure('ReadTimeout: timeout').message).toBe('The site did not answer.')
  })

  it('falls back to a generic sentence for anything else', () => {
    expect(describeReaderFailure('something odd').message).toBe('Spyglass could not read the page.')
    expect(describeReaderFailure('HTTP 500').message).toBe('The site had a problem and could not show the page.')
  })
})
