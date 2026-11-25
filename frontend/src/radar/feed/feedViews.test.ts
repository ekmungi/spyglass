// Tests for the Feed's exclusive views: which one an address shows and the parameters a choice writes.
import { describe, expect, it } from 'vitest'
import { currentView, paramsForView } from './feedViews'

describe('currentView', () => {
  it('is Everything when no view parameter is present, whatever other filters are', () => {
    expect(currentView({}, true)).toBe('everything')
    expect(currentView({ section: 'health', kind: 'paper' }, true)).toBe('everything')
  })

  it('reads each view parameter', () => {
    expect(currentView({ missed: 'true' }, false)).toBe('missed')
    expect(currentView({ saved: 'true' }, false)).toBe('saved')
    expect(currentView({ from_user: 'true' }, false)).toBe('from_you')
    expect(currentView({ filing: 'waiting' }, true)).toBe('to_file')
  })

  it('shows the first of several in the order Missed, Saved, From you, To file', () => {
    expect(currentView({ filing: 'waiting', from_user: 'true', saved: 'true', missed: 'true' }, true)).toBe('missed')
    expect(currentView({ filing: 'waiting', from_user: 'true', saved: 'true' }, true)).toBe('saved')
    expect(currentView({ filing: 'waiting', from_user: 'true' }, true)).toBe('from_you')
  })

  it('ignores the To file parameter where filing is not set up', () => {
    expect(currentView({ filing: 'waiting' }, false)).toBe('everything')
  })
})

describe('paramsForView', () => {
  it('sets the chosen view and drops the others, keeping other filters', () => {
    expect(paramsForView({ saved: 'true', missed: 'true', section: 'health' }, 'from_you')).toEqual({ section: 'health', from_user: 'true' })
    expect(paramsForView({ from_user: 'true' }, 'to_file')).toEqual({ filing: 'waiting' })
  })

  it('clears every view parameter for Everything and does not change the input', () => {
    const before = { saved: 'true', filing: 'waiting', q: 'x' }
    expect(paramsForView(before, 'everything')).toEqual({ q: 'x' })
    expect(before).toEqual({ saved: 'true', filing: 'waiting', q: 'x' })
  })
})
