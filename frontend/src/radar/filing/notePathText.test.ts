// Tests for the vault-place helpers used by the plan and Filed recently in narrow columns.
import { describe, expect, it } from 'vitest'
import { pathSegments, splitForMiddleTruncation, splitNotePath } from './notePathText'

describe('pathSegments', () => {
  it('splits a folder path at either kind of slash and drops empty parts', () => {
    expect(pathSegments('03 RESOURCES/Papers/Medicine')).toEqual(['03 RESOURCES', 'Papers', 'Medicine'])
    expect(pathSegments('/a\\b//c/')).toEqual(['a', 'b', 'c'])
  })

  it('gives nothing for an empty place', () => {
    expect(pathSegments('')).toEqual([])
  })
})

describe('splitNotePath', () => {
  it('separates the folders from the file name', () => {
    expect(splitNotePath('03 RESOURCES/Papers/20261112_Note.md')).toEqual({ folders: ['03 RESOURCES', 'Papers'], name: '20261112_Note.md' })
  })

  it('treats a bare name as a name with no folders', () => {
    expect(splitNotePath('Note.md')).toEqual({ folders: [], name: 'Note.md' })
  })
})

describe('splitForMiddleTruncation', () => {
  it('keeps the end of a long name visible', () => {
    const { head, tail } = splitForMiddleTruncation('20261112_Sample_Paper_On_Device_Rules.md')
    expect(tail).toBe('evice_Rules.md')
    expect(head + tail).toBe('20261112_Sample_Paper_On_Device_Rules.md')
  })

  it('leaves a short name whole', () => {
    expect(splitForMiddleTruncation('Note.md')).toEqual({ head: 'Note.md', tail: '' })
  })
})
