// Tests for the Settings category manager: list, add (+), remove (x).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CategorySettingsSection } from './CategorySettingsSection'

const CATS = [
  { name: 'Healthcare AI', count: 5 },
  { name: 'Robotics', count: 2 },
]

function stubFetch() {
  return vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') return new Response(JSON.stringify({ name: 'X' }), { status: 201 })
    if (init?.method === 'DELETE')
      return new Response(JSON.stringify({ deleted: 'X' }), { status: 200 })
    return new Response(JSON.stringify(CATS), { status: 200 }) // GET /api/categories
  })
}

describe('CategorySettingsSection', () => {
  beforeEach(() => vi.stubGlobal('fetch', stubFetch()))
  afterEach(() => vi.unstubAllGlobals())

  it('lists the managed categories as chips', async () => {
    render(<CategorySettingsSection />)
    expect(await screen.findByText('Healthcare AI')).toBeInTheDocument()
    expect(screen.getByText('Robotics')).toBeInTheDocument()
  })

  it('adds a category via + then the name input (POST)', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    render(<CategorySettingsSection />)
    await screen.findByText('Healthcare AI')
    fireEvent.click(screen.getByRole('button', { name: /add category/i }))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Product & Career' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => {
      const post = stub.mock.calls.find((c) => c[1]?.method === 'POST')
      expect(post).toBeDefined()
      expect(JSON.parse(String(post![1]!.body))).toEqual({ name: 'Product & Career' })
    })
  })

  it('removes a category via x after confirm (DELETE)', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategorySettingsSection />)
    await screen.findByText('Robotics')
    fireEvent.click(screen.getByRole('button', { name: /remove robotics/i }))
    await waitFor(() => {
      const del = stub.mock.calls.find((c) => c[1]?.method === 'DELETE')
      expect(del).toBeDefined()
      expect(String(del![0])).toContain('/api/categories/Robotics')
    })
  })

  it('does not delete when the confirm is cancelled', async () => {
    const stub = stubFetch()
    vi.stubGlobal('fetch', stub)
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<CategorySettingsSection />)
    await screen.findByText('Robotics')
    fireEvent.click(screen.getByRole('button', { name: /remove robotics/i }))
    expect(stub.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false)
  })
})
