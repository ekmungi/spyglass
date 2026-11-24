// Tests for the gate that shows the first-start page in place of the app when one is needed.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { FirstStart } from '../../api/types'
import { FirstStartGate } from './FirstStartGate'

const api = vi.hoisted(() => ({ getFirstStart: vi.fn(), getExtensionFolder: vi.fn(), dismissSetupGuide: vi.fn() }))
vi.mock('../../api/client', async (original) => ({ ...(await original<typeof import('../../api/client')>()), ...api }))

const ANSWER: FirstStart = { needed: false, data_dir: 'C:\\Data', vault_path: null, browsers: [] }

beforeEach(() => {
  vi.clearAllMocks()
  api.getExtensionFolder.mockResolvedValue({ folder: 'C:\\Spyglass\\browser-extension' })
  api.dismissSetupGuide.mockResolvedValue(null)
})

afterEach(() => cleanup())

const app = <p>The normal app</p>

describe('FirstStartGate', () => {
  it('keeps showing the app while the answer is pending, then shows the welcome page when needed', async () => {
    let answer: (value: FirstStart) => void = () => {}
    api.getFirstStart.mockReturnValue(new Promise((resolve) => (answer = resolve)))
    render(<FirstStartGate>{app}</FirstStartGate>)
    expect(screen.getByText('The normal app')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Welcome to Spyglass' })).toBeNull()
    answer({ ...ANSWER, needed: true })
    expect(await screen.findByRole('heading', { name: 'Welcome to Spyglass' })).toBeInTheDocument()
    expect(screen.queryByText('The normal app')).toBeNull()
  })

  it('shows the app and no welcome page when nothing is needed', async () => {
    api.getFirstStart.mockResolvedValue(ANSWER)
    render(<FirstStartGate>{app}</FirstStartGate>)
    await waitFor(() => expect(api.getFirstStart).toHaveBeenCalled())
    expect(screen.getByText('The normal app')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Welcome to Spyglass' })).toBeNull()
  })

  it('shows the welcome page for a browser guide even when no first start is needed', async () => {
    api.getFirstStart.mockResolvedValue({ ...ANSWER, browsers: [{ id: 'chrome', name: 'Chrome' }] })
    render(<FirstStartGate>{app}</FirstStartGate>)
    expect(await screen.findByRole('button', { name: 'Skip for now' })).toBeInTheDocument()
    expect(screen.queryByText('The normal app')).toBeNull()
  })

  it('shows the app as today when the call fails', async () => {
    api.getFirstStart.mockRejectedValue(new ApiError('Not found', { status: 404, kind: 'http', path: '/x' }))
    render(<FirstStartGate>{app}</FirstStartGate>)
    await waitFor(() => expect(api.getFirstStart).toHaveBeenCalled())
    expect(screen.getByText('The normal app')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Welcome to Spyglass' })).toBeNull()
  })

  it('returns to the app when the welcome page finishes', async () => {
    api.getFirstStart.mockResolvedValue({ ...ANSWER, browsers: [{ id: 'chrome', name: 'Chrome' }] })
    render(<FirstStartGate>{app}</FirstStartGate>)
    fireEvent.click(await screen.findByRole('button', { name: 'Skip for now' }))
    expect(await screen.findByText('The normal app')).toBeInTheDocument()
  })
})
