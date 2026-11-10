// Tests for the linked-session helpers.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText, linkLine, referenceText } from './link'

describe('referenceText', () => {
  it('names the items by code after the task', () => {
    expect(referenceText([12, 15], 'Compare these.')).toBe('Compare these.\n\nItems: #12, #15')
  })
  it('is just the codes without a task, and just the task without items', () => {
    expect(referenceText([12])).toBe('#12')
    expect(referenceText([], 'Make the brief.')).toBe('Make the brief.')
    expect(referenceText([])).toBe('')
  })
})

describe('linkLine', () => {
  it('says whether a session is linked, waiting or absent', () => {
    expect(linkLine(null)).toBe('No linked Claude session')
    expect(linkLine({ linked: false, linked_at: null, last_seen: null, waiting: true })).toBe(
      'Waiting for the new Claude session',
    )
    const now = new Date().toISOString()
    expect(linkLine({ linked: true, linked_at: now, last_seen: now, waiting: false })).toMatch(
      /^Linked to Claude, last heard /,
    )
    expect(linkLine({ linked: true, linked_at: now, last_seen: now, waiting: true })).toBe(
      'Linked to Claude, a new session is waiting to link',
    )
    expect(
      linkLine({ linked: false, idle: true, linked_at: now, last_seen: now, waiting: false }),
    ).toMatch(/^Linked session idle, last heard /)
  })

  it('says when a new session has not linked after a while', () => {
    const opened = Date.parse('2026-10-15T08:00:00Z')
    const waiting = { linked: false, linked_at: null, last_seen: null, waiting: true,
      waiting_since: new Date(opened).toISOString() }
    expect(linkLine(waiting, opened + 30_000)).toBe('Waiting for the new Claude session')
    expect(linkLine(waiting, opened + 120_000)).toMatch(/^The new Claude session has not linked/)
  })
})

describe('copyText', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reports whether the browser let it copy', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await expect(copyText('#12')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('#12')
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error()) } })
    await expect(copyText('#12')).resolves.toBe(false)
  })
})
