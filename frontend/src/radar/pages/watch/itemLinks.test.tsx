// Tests for the item links on the Watch page: opening an item records Watch as the page the reader
// came from, so Back in the reader returns there instead of falling back to Today.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { RadarItem } from '../../api/types'
import type { Track } from '../../api/trackTypes'
import { readerOrigin } from '../../router'
import { TrackRow } from './TrackRow'
import { WatchRow } from './WatchRow'
import { entry, recentItem } from './testFixtures'

beforeEach(() => {
  window.history.replaceState(null, '', '/#/watch')
})
afterEach(cleanup)

function track(): Track {
  const item = { id: 41, title: 'A topic story', headline: 'A topic story' } as unknown as RadarItem
  return {
    id: 1, label: 'Foundation models', query: 'foundation models', section: 'ai' as Track['section'],
    section_label: 'AI', kind: 'keyword' as Track['kind'], active: true, created_at: '2026-11-01T00:00:00Z',
    from_item_id: null, last_run_at: null, last_new: 0, recent: [item],
  }
}

describe('Watch item links', () => {
  it('a name\'s latest item opens the reader with Watch as its origin', () => {
    render(
      <ul>
        <WatchRow entry={entry({ id: 1, name: 'Acme', recent: [recentItem(40, 'Acme story') as unknown as RadarItem] })} busy={false} />
      </ul>,
    )
    fireEvent.click(screen.getByRole('link', { name: 'Acme story' }))
    expect(window.location.hash).toBe('#/item/40')
    expect(readerOrigin()).toEqual({ name: 'watch' })
  })

  it('a followed topic\'s latest item opens the reader with Watch as its origin', () => {
    render(
      <ul>
        <TrackRow track={track()} busy={false} menu={[]} />
      </ul>,
    )
    fireEvent.click(screen.getByRole('link', { name: 'A topic story' }))
    expect(window.location.hash).toBe('#/item/41')
    expect(readerOrigin()).toEqual({ name: 'watch' })
  })
})
