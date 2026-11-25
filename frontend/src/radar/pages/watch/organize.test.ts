// layoutRegister: the one-time layout of the Watch page (groups, paused names, suggestion rows, rejected names).
import { describe, expect, it } from 'vitest'
import { layoutRegister } from './organize'
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

  it('passes the rejected names through for the Not of interest list', () => {
    const reg = { ...register(), rejected: [entry({ id: 30, name: 'Nope Inc', status: 'rejected' })] }
    expect(layoutRegister(reg).rejected.map((e) => e.name)).toEqual(['Nope Inc'])
  })
})
