// Tests for the Activity tab: per-source run history.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunRow } from '../lib/types'
import { ActivityTab } from './ActivityTab'

const runs: RunRow[] = [
  {
    id: 2,
    source: 'raindrop',
    status: 'error',
    detail: 'Raindrop API returned 401',
    started_at: '2026-06-10T09:00:00Z',
    finished_at: '2026-06-10T09:00:02Z',
  },
  {
    id: 1,
    source: 'rss',
    status: 'ok',
    detail: '3 new of 14 fetched',
    started_at: '2026-06-10T08:59:00Z',
    finished_at: '2026-06-10T08:59:10Z',
  },
]

describe('ActivityTab', () => {
  it('renders one row per run with source, status, and detail', () => {
    render(<ActivityTab runs={runs} />)
    expect(screen.getByText('raindrop')).toBeInTheDocument()
    expect(screen.getByText('Raindrop API returned 401')).toBeInTheDocument()
    expect(screen.getByText('3 new of 14 fetched')).toBeInTheDocument()
  })

  it('shows an empty message when there are no runs yet', () => {
    render(<ActivityTab runs={[]} />)
    expect(screen.getByText(/no runs/i)).toBeInTheDocument()
  })
})
