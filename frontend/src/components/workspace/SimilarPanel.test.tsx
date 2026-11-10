// Tests for SimilarPanel: fetches similar articles and opens one on click.
// Results carry a cosine score, shown subtly next to each title.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SimilarPanel } from './SimilarPanel'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'

describe('SimilarPanel', () => {
  it('lists similar articles with their scores and opens one on click', async () => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([
      { ...makeCard({ id: 2, title: 'Neighbour' }), score: 0.81 },
    ])
    const onOpen = vi.fn()
    render(<SimilarPanel cardId={1} onOpen={onOpen} />)
    await waitFor(() => expect(screen.getByText('Neighbour')).toBeInTheDocument())
    // The score shows subtly beside the title.
    expect(screen.getByText('0.81')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Neighbour'))
    expect(onOpen).toHaveBeenCalledWith(2)
  })

  it('renders nothing when there are no similar articles', async () => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
    const { container } = render(<SimilarPanel cardId={1} onOpen={() => {}} />)
    await waitFor(() => expect(api.getSimilar).toHaveBeenCalled())
    expect(container.textContent).not.toContain('Similar')
  })
})
