// Tests for finding the Profile tab that holds a validation problem.
import { describe, expect, it } from 'vitest'
import type { Profile } from '../../api/types'
import { firstTabWithProblem } from './profileTabs'
import { validateProfile } from './validate'

const good: Profile = {
  version: 1,
  statement: 'Someone who follows AI.',
  sections: [{ key: 'models', label: 'Models', description: '' }],
  topics: [{ name: 'Open-weight models', section: 'models' }],
  avoid: ['Sports'],
}

const check = (profile: Profile) => firstTabWithProblem(validateProfile(profile), profile)

describe('firstTabWithProblem', () => {
  it('finds nothing in a profile that can be saved', () => {
    expect(check(good)).toBeNull()
  })

  it('names the tab of the first problem in strip order', () => {
    expect(check({ ...good, statement: ' ', avoid: [''] })).toBe('about')
    expect(check({ ...good, sections: [{ key: 'models', label: '', description: '' }], avoid: [''] })).toBe('sections')
    expect(check({ ...good, topics: [{ name: '', section: '' }], avoid: [''] })).toBe('topics')
    expect(check({ ...good, avoid: [''] })).toBe('avoid')
  })

  it('sends a too-long list to its own tab', () => {
    expect(check({ ...good, avoid: Array.from({ length: 51 }, (_, index) => `Subject ${index}`) })).toBe('avoid')
    expect(check({ ...good, topics: Array.from({ length: 101 }, (_, index) => ({ name: `Topic ${index}`, section: '' })) })).toBe('topics')
  })
})
