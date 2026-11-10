// Tests for FeedRow: single feed row with inline rename, toggle, health badge, delete.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FeedData } from '../lib/types'
import { FeedRow } from './FeedRow'

vi.mock('../lib/api')

const okFeed: FeedData = {
  id: 1,
  feed_url: 'https://example.com/feed.xml',
  name: 'Example Feed',
  name_overridden: false,
  kind: 'rss',
  enabled: true,
  last_fetch_status: 'ok',
  last_fetch_at: '2026-06-29T10:00:00Z',
  last_error: null,
  item_count: 42,
  added_via: 'import',
}

const errorFeed: FeedData = {
  ...okFeed,
  id: 2,
  name: 'Broken Feed',
  last_fetch_status: 'error',
  last_error: 'connection timeout',
}

const nullFeed: FeedData = {
  ...okFeed,
  id: 3,
  name: 'New Feed',
  last_fetch_status: null,
  last_fetch_at: null,
}

describe('FeedRow', () => {
  const onUpdate = vi.fn()
  const onDelete = vi.fn()

  beforeEach(() => {
    onUpdate.mockClear()
    onDelete.mockClear()
  })

  it('renders name, url, item_count, and health badge for ok status', () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    expect(screen.getByText('Example Feed')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/feed.xml')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    const badge = screen.getByText('ok')
    expect(badge.className).toContain('text-accent2')
  })

  it('shows error color badge for error status', () => {
    render(<FeedRow feed={errorFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    const badge = screen.getByText('error')
    expect(badge.className).toContain('text-accent')
    expect(badge.className).not.toContain('text-accent2')
  })

  it('shows neutral badge when status is null', () => {
    render(<FeedRow feed={nullFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    expect(screen.getByText('never fetched')).toBeInTheDocument()
  })

  it('toggle calls onUpdate with enabled false when currently enabled', async () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    const toggle = screen.getByRole('checkbox')
    fireEvent.click(toggle)
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(1, { enabled: false }))
  })

  it('toggle calls onUpdate with enabled true when currently disabled', async () => {
    const disabledFeed = { ...okFeed, enabled: false }
    render(<FeedRow feed={disabledFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    const toggle = screen.getByRole('checkbox')
    fireEvent.click(toggle)
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(1, { enabled: true }))
  })

  it('inline rename: clicking name enters edit mode', () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    fireEvent.click(screen.getByText('Example Feed'))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('inline rename: blur with changed value calls onUpdate with name', async () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    fireEvent.click(screen.getByText('Example Feed'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Renamed Feed' } })
    fireEvent.blur(input)
    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith(1, { name: 'Renamed Feed' }),
    )
  })

  it('inline rename: blur with unchanged value does NOT call onUpdate', async () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    fireEvent.click(screen.getByText('Example Feed'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Example Feed' } })
    fireEvent.blur(input)
    await waitFor(() => expect(onUpdate).not.toHaveBeenCalled())
  })

  it('delete: first click shows confirm button', () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument()
  })

  it('delete: confirm calls onDelete with feed id', async () => {
    render(<FeedRow feed={okFeed} onUpdate={onUpdate} onDelete={onDelete} />)
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(1))
  })
})
