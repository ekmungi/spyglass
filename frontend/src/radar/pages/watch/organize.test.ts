// layoutRegister: the one-time layout of the Watch page (groups, paused names, suggestion rows, rejected
// names); withStatuses and registerWithStatuses: names' statuses changed in a copy; groupSteps: how far
// "Move up" and "Move down" go.
import { describe, expect, it } from 'vitest'
import { groupSteps, layoutRegister, registerWithStatuses, withStatuses } from './organize'
import { entry, register } from './testFixtures'

describe('layoutRegister', () => {
  it('keeps a muted name out of its group and lists it as paused with that group', () => {
    const base = register()
    const reg = {
      ...base,
      categories: [
        {
          name: 'Imaging AI',
          entities: [
            entry({ id: 1, name: 'Alpha Scopes' }),
            entry({ id: 2, name: 'Zeta Vision', status: 'muted' }),
          ],
        },
      ],
    }
    const layout = layoutRegister(reg)
    expect(layout.groups).toHaveLength(1)
    expect(layout.groups[0].name).toBe('Imaging AI')
    expect(layout.groups[0].entities.map((e) => e.name)).toEqual(['Alpha Scopes'])
    expect(layout.paused).toHaveLength(1)
    expect(layout.paused[0].entity.name).toBe('Zeta Vision')
    expect(layout.paused[0].group).toBe('Imaging AI')
  })

  it('hides a group with no active name but still lists its paused names', () => {
    const layout = layoutRegister(register()) // Regulators holds only a muted name
    expect(layout.groups.map((g) => g.name)).toEqual(['Imaging AI'])
    expect(layout.paused.map((p) => [p.entity.name, p.group])).toEqual([['FDA', 'Regulators']])
  })

  it('keeps the groups and the names in the order the server sent', () => {
    const reg = {
      ...register(),
      categories: [
        { name: 'Zebra', entities: [entry({ id: 1, name: 'B' }), entry({ id: 2, name: 'A' })] },
        { name: 'Apple', entities: [entry({ id: 3, name: 'C' })] },
      ],
    }
    const layout = layoutRegister(reg)
    expect(layout.groups.map((g) => g.name)).toEqual(['Zebra', 'Apple'])
    expect(layout.groups[0].entities.map((e) => e.name)).toEqual(['B', 'A'])
  })

  it('orders the suggestion rows by the profile, most-named first inside a row', () => {
    const reg = {
      ...register(),
      sections: [
        { key: 'devices', label: 'Medical devices' },
        { key: 'ai', label: 'AI research' },
      ],
      suggested: [
        entry({ id: 10, name: 'Few', status: 'suggested', section: 'ai', count: 1 }),
        entry({ id: 11, name: 'Many', status: 'suggested', section: 'ai', count: 5 }),
        entry({ id: 12, name: 'Device Co', status: 'suggested', section: 'devices', count: 2 }),
      ],
    }
    const layout = layoutRegister(reg)
    expect(layout.rows.map((r) => r.label)).toEqual(['Medical devices', 'AI research'])
    expect(layout.rows[1].entities.map((e) => e.name)).toEqual(['Many', 'Few'])
    expect(layout.rows[0].topic).toBe(false)
  })

  it('gives each topic search its own row after the profile sections', () => {
    const reg = {
      ...register(),
      sections: [{ key: 'ai', label: 'AI research' }],
      suggested: [
        entry({ id: 10, name: 'Profile Name', status: 'suggested', section: 'ai', count: 3 }),
        entry({ id: 11, name: 'Agent One', status: 'suggested', section: '', topic: 'agents', count: 0 }),
        entry({ id: 12, name: 'Agent Two', status: 'suggested', section: 'ai', topic: 'agents', count: 0 }),
        entry({ id: 13, name: 'Robot One', status: 'suggested', section: '', topic: 'robots', count: 0 }),
      ],
    }
    const layout = layoutRegister(reg)
    expect(layout.rows.map((r) => [r.label, r.topic])).toEqual([
      ['AI research', false],
      ['agents', true],
      ['robots', true],
    ])
    // A topic-search name never also appears in a profile-section row.
    expect(layout.rows[0].entities.map((e) => e.name)).toEqual(['Profile Name'])
    expect(layout.rows[1].entities.map((e) => e.name)).toEqual(['Agent One', 'Agent Two'])
  })

  it('collects names whose section matches no profile section in a trailing Other row', () => {
    const reg = {
      ...register(),
      sections: [{ key: 'ai', label: 'AI research' }],
      suggested: [entry({ id: 10, name: 'Stray', status: 'suggested', section: 'gone', count: 1 })],
    }
    const layout = layoutRegister(reg)
    expect(layout.rows.map((r) => r.label)).toEqual(['AI research', 'Other'])
    expect(layout.rows[1].entities.map((e) => e.name)).toEqual(['Stray'])
  })

  it('leaves out a suggestion no collection has placed (no topic and no section), even if the server sends one', () => {
    const reg = {
      ...register(),
      sections: [{ key: 'ai', label: 'AI research' }],
      suggested: [
        entry({ id: 10, name: 'Legacy Co', status: 'suggested', section: '', count: 0 }),
        entry({ id: 11, name: 'Stray', status: 'suggested', section: 'gone', count: 1 }),
      ],
    }
    const layout = layoutRegister(reg)
    // "Other" still holds a placed name whose section has left the profile.
    expect(layout.rows.map((r) => r.label)).toEqual(['AI research', 'Other'])
    expect(layout.rows.flatMap((r) => r.entities).map((e) => e.name)).toEqual(['Stray'])
  })

  it('passes the rejected names through for the Not of interest list', () => {
    const reg = { ...register(), rejected: [entry({ id: 30, name: 'Nope Inc', status: 'rejected' })] }
    expect(layoutRegister(reg).rejected.map((e) => e.name)).toEqual(['Nope Inc'])
  })

  it("carries each group's weekly count, or null when the server did not send one", () => {
    const reg = {
      ...register(),
      categories: [
        { name: 'Counted', week_count: 4, entities: [entry({ id: 1, name: 'A' })] },
        { name: 'Uncounted', entities: [entry({ id: 2, name: 'B' })] },
      ],
    }
    expect(layoutRegister(reg).groups.map((g) => [g.name, g.weekCount])).toEqual([
      ['Counted', 4],
      ['Uncounted', null],
    ])
  })
})

describe('withStatuses', () => {
  it('changes the given names where they are shown and moves nothing', () => {
    const layout = layoutRegister(register())
    const changed = withStatuses(layout, new Map([[1, 'muted'], [3, 'active']]))
    expect(changed.groups[0].entities.map((e) => [e.name, e.status])).toEqual([
      ['Alpha Scopes', 'muted'],
      ['Zeta Vision', 'active'],
    ])
    expect(changed.paused.map((p) => [p.entity.name, p.entity.status, p.group])).toEqual([['FDA', 'active', 'Regulators']])
    // The layout it was given is left as it was.
    expect(layout.groups[0].entities[0].status).toBe('active')
  })

  it('returns the same layout when there is nothing to change', () => {
    const layout = layoutRegister(register())
    expect(withStatuses(layout, new Map())).toBe(layout)
  })
})

describe('registerWithStatuses', () => {
  it('changes the given followed names in a copy, so the next layout puts each where its status says', () => {
    const before = register()
    const after = registerWithStatuses(before, new Map([[2, 'muted'], [3, 'active']]))
    const layout = layoutRegister(after)
    expect(layout.paused.map((p) => p.entity.name)).toEqual(['Zeta Vision'])
    expect(layout.groups.map((g) => g.name)).toEqual(['Imaging AI', 'Regulators'])
    expect(before.categories[0].entities[1].status).toBe('active')
  })

  it('moves a watched suggestion into its group and a rejected one into the rejected list, in name order', () => {
    const before = {
      ...register(),
      suggested: [
        entry({ id: 9, name: 'Gamma Labs', status: 'suggested', category: 'Imaging AI' }),
        entry({ id: 10, name: 'Beta Org', status: 'suggested', category: '' }),
        entry({ id: 11, name: 'Kappa Inc', status: 'suggested' }),
      ],
      rejected: [entry({ id: 30, name: 'Alpha News', status: 'rejected' }), entry({ id: 31, name: 'Zed Corp', status: 'rejected' })],
    }
    const after = registerWithStatuses(before, new Map([[9, 'active'], [10, 'active'], [11, 'rejected']]))
    // The server lists names by name inside a group, and puts a name with no group in "Other", last.
    expect(after.categories.map((c) => [c.name, c.entities.map((e) => e.name)])).toEqual([
      ['Imaging AI', ['Alpha Scopes', 'Gamma Labs', 'Zeta Vision']],
      ['Regulators', ['FDA']],
      ['Other', ['Beta Org']],
    ])
    expect(after.categories[0].entities[1].status).toBe('active')
    expect(after.suggested).toEqual([])
    expect(after.rejected.map((e) => [e.name, e.status])).toEqual([
      ['Alpha News', 'rejected'],
      ['Kappa Inc', 'rejected'],
      ['Zed Corp', 'rejected'],
    ])
    expect(before.suggested).toHaveLength(3)
  })

  it('takes a name back out of its group or the rejected list when its status is "suggested"', () => {
    const before = { ...register(), rejected: [entry({ id: 30, name: 'Alpha News', status: 'rejected' })] }
    const after = registerWithStatuses(before, new Map([[2, 'suggested'], [30, 'suggested']]))
    expect(after.categories[0].entities.map((e) => e.name)).toEqual(['Alpha Scopes'])
    expect(after.suggested.map((e) => [e.name, e.status])).toEqual([
      ['Alpha News', 'suggested'],
      ['Gamma Labs', 'suggested'],
      ['Zeta Vision', 'suggested'],
    ])
    expect(after.rejected).toEqual([])
  })
})

describe('groupSteps', () => {
  const order = ['First', 'Hidden', 'Middle', 'Last']
  const shown = ['First', 'Middle', 'Last']

  it('moves one place when the neighbour is shown', () => {
    expect(groupSteps(order, shown, 'Last', 'up')).toBe(1)
    expect(groupSteps(order, shown, 'Middle', 'down')).toBe(1)
  })

  it('moves past a hidden group so the shown order changes', () => {
    expect(groupSteps(order, shown, 'First', 'down')).toBe(2)
    expect(groupSteps(order, shown, 'Middle', 'up')).toBe(2)
  })

  it('is 0 at either end of the shown groups, or for a group it does not know', () => {
    expect(groupSteps(order, shown, 'First', 'up')).toBe(0)
    expect(groupSteps(order, shown, 'Last', 'down')).toBe(0)
    expect(groupSteps(['Hidden', 'Only'], ['Only'], 'Only', 'up')).toBe(0)
    expect(groupSteps(order, shown, 'Nowhere', 'down')).toBe(0)
  })
})
