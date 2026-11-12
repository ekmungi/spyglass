// Tests for the assistant's engine choice: stored pick, server default, unavailable engines.
import { describe, expect, it } from 'vitest'
import type { Engine } from '../api/types'
import { decodeChoice, encodeChoice, engineGroups, resolveChoice } from './engineChoice'

/** A minimal engine row. */
function engine(id: string, overrides: Partial<Engine> = {}): Engine {
  return { id, label: id.toUpperCase(), kind: 'api', available: true, reason: null, models: [{ id: `${id}-m1`, label: 'M1' }, { id: `${id}-m2`, label: 'M2' }], default_model: `${id}-m1`, ...overrides }
}

describe('resolveChoice', () => {
  it('keeps a stored pick whose engine is available', () => {
    expect(resolveChoice([engine('a'), engine('b')], { engine: 'b', model: 'b-m2' })).toEqual({ engine: 'b', model: 'b-m2' })
  })

  it('uses the engine default model when the stored model is gone', () => {
    expect(resolveChoice([engine('a')], { engine: 'a', model: 'retired' })).toEqual({ engine: 'a', model: 'a-m1' })
  })

  it('falls back to the server default engine when the pick is unavailable', () => {
    const engines = [engine('a'), engine('b', { is_default: true }), engine('c', { available: false, reason: 'No key' })]
    expect(resolveChoice(engines, { engine: 'c', model: null })).toEqual({ engine: 'b', model: 'b-m1' })
  })

  it('falls back to the first available engine when none is marked default', () => {
    expect(resolveChoice([engine('a', { available: false }), engine('b')], null)).toEqual({ engine: 'b', model: 'b-m1' })
  })

  it('preselects the first available engine when the server default is itself unavailable', () => {
    const engines = [engine('a', { is_default: true, available: false, reason: 'No API key' }), engine('b'), engine('c')]
    expect(resolveChoice(engines, null)).toEqual({ engine: 'b', model: 'b-m1' })
    expect(resolveChoice(engines, { engine: 'a', model: 'a-m1' })).toEqual({ engine: 'b', model: 'b-m1' })
  })

  it('returns null when no engine is available', () => {
    expect(resolveChoice([engine('a', { available: false })], null)).toBeNull()
    expect(resolveChoice([], null)).toBeNull()
  })
})

describe('select encoding', () => {
  it('round-trips a choice through the select value', () => {
    expect(decodeChoice(encodeChoice({ engine: 'a', model: 'a-m2' }))).toEqual({ engine: 'a', model: 'a-m2' })
    expect(decodeChoice(encodeChoice({ engine: 'local', model: null }))).toEqual({ engine: 'local', model: null })
    expect(decodeChoice('')).toBeNull()
  })

  it('lists unavailable engines as a disabled option carrying their reason', () => {
    const groups = engineGroups([engine('a'), engine('b', { available: false, reason: 'No API key saved.' })])
    expect(groups[0].options.map((option) => option.value)).toEqual(['a::a-m1', 'a::a-m2'])
    expect(groups[1]).toEqual({ label: 'B (not available)', options: [{ value: 'unavailable::b', label: 'No API key saved.', disabled: true }] })
  })
})
