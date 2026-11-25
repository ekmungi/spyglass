// Tests for the reading list: the list the reader last opened an item from, and where an item sits in it.
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { neighbours, resetReadingList, setReadingList, useReadingList } from './readingList'

afterEach(() => resetReadingList())

const LIST = { label: 'Today', ids: [11, 12, 13, 14] }

describe('neighbours', () => {
  it('has no previous item at the start of the list', () => {
    expect(neighbours(LIST, 11)).toEqual({ index: 0, total: 4, previous: null, next: 12 })
  })

  it('has both neighbours in the middle', () => {
    expect(neighbours(LIST, 13)).toEqual({ index: 2, total: 4, previous: 12, next: 14 })
  })

  it('has no next item at the end of the list', () => {
    expect(neighbours(LIST, 14)).toEqual({ index: 3, total: 4, previous: 13, next: null })
  })

  it('is null for an item that is not in the list, or when there is no list', () => {
    expect(neighbours(LIST, 99)).toBeNull()
    expect(neighbours(null, 11)).toBeNull()
  })
})

describe('setReadingList and useReadingList', () => {
  it('starts empty and hands every reader the list that was set last', () => {
    const { result } = renderHook(() => useReadingList())
    expect(result.current).toBeNull()
    act(() => setReadingList('the Feed', [5, 6]))
    expect(result.current).toEqual({ label: 'the Feed', ids: [5, 6] })
    act(() => setReadingList('Today', [7]))
    expect(result.current).toEqual({ label: 'Today', ids: [7] })
  })

  it('keeps its own copy of the ids, so a later change to the caller array does not move it', () => {
    const ids = [1, 2, 3]
    setReadingList('Today', ids)
    ids.push(4)
    const { result } = renderHook(() => useReadingList())
    expect(result.current?.ids).toEqual([1, 2, 3])
  })
})
