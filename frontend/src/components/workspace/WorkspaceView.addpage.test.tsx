// WorkspaceView wiring for Add page: reload + open the new card in the reader.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../lib/api'
import { makeCard } from '../../test/fixtures'
import { WorkspaceView } from './WorkspaceView'

// virtua needs real layout (absent in jsdom); render its children directly.
vi.mock('virtua', () => ({
  Virtualizer: ({ children }: { children?: import('react').ReactNode }) => <>{children}</>,
}))

const cards = [
  makeCard({ id: 1, title: 'First card' }),
  makeCard({ id: 2, title: 'Added page card' }),
]

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const respond = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
    if (url.includes('/fulltext')) return respond({ status: 'ok', markdown: 'Stored text.' })
    if (url.includes('/api/categories')) return respond([])
    return respond({})
  })
}

function renderView(overrides: Partial<Parameters<typeof WorkspaceView>[0]> = {}) {
  return render(
    <WorkspaceView
      cards={cards}
      refreshing={false}
      onRefresh={() => {}}
      onOpenClaude={() => {}}
      onUpdate={() => {}}
      onMerge={() => {}}
      onDelete={() => {}}
      onOpenExternal={() => {}}
      onReload={() => {}}
      {...overrides}
    />,
  )
}

describe('WorkspaceView add page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSimilar').mockResolvedValue([])
    vi.stubGlobal('fetch', stubFetch())
    vi.stubGlobal('scrollTo', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('adding a page reloads the cards and opens the new card in the reader', async () => {
    const onReload = vi.fn()
    vi.spyOn(api, 'addPage').mockResolvedValue({
      ...makeCard({ id: 2, title: 'Added page card' }),
      status: 'created',
    })
    renderView({ onReload })
    fireEvent.click(screen.getByRole('button', { name: /add page/i }))
    fireEvent.change(screen.getByPlaceholderText(/page url/i), {
      target: { value: 'https://example.com/post' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    // The list reloads so the new card appears, and the reader opens on it.
    await waitFor(() => expect(onReload).toHaveBeenCalled())
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
  })

  it('an existing page opens its card in the reader without duplicating anything', async () => {
    const onReload = vi.fn()
    vi.spyOn(api, 'addPage').mockResolvedValue({
      ...makeCard({ id: 2, title: 'Added page card' }),
      status: 'exists',
    })
    renderView({ onReload })
    fireEvent.click(screen.getByRole('button', { name: /add page/i }))
    fireEvent.change(screen.getByPlaceholderText(/page url/i), {
      target: { value: 'https://example.com/dup' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    await waitFor(() => expect(onReload).toHaveBeenCalled())
    expect(await screen.findByText('Stored text.')).toBeInTheDocument()
  })
})
