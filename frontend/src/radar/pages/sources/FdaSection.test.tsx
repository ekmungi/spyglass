// Tests for the FDA group of the Sources page: the explanation, the switch, saving the lists,
// refusing characters the server would refuse, and showing a failed last run.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { CollectorRow } from './api'
import { FdaSection } from './FdaSection'

const api = vi.hoisted(() => ({ loadFdaSettings: vi.fn(), saveFdaSettings: vi.fn() }))
vi.mock('./fdaApi', async (importOriginal) => ({ ...(await importOriginal<typeof import('./fdaApi')>()), ...api }))

const recent = new Date(Date.now() - 3600_000).toISOString()
const row = (over: Partial<CollectorRow> = {}): CollectorRow => ({
  key: 'fda', label: 'FDA device decisions', status: 'ok', detail: '2 new of 5 found', lastRun: recent, newItems: 2, enabled: null, ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.loadFdaSettings.mockResolvedValue({ enabled: true, productCodes: 'QAS', keywords: '' })
  api.saveFdaSettings.mockImplementation(async (change) => ({ enabled: true, productCodes: 'QAS', keywords: '', ...change }))
})

describe('FdaSection', () => {
  it('explains the source and shows the last run', async () => {
    render(<FdaSection collectors={[row()]} />)
    expect(screen.getByRole('heading', { name: 'FDA device decisions' })).toBeInTheDocument()
    expect(screen.getByText(/Once a day Spyglass asks the public FDA database/)).toBeInTheDocument()
    expect(screen.getByText(/api\.fda\.gov/)).toBeInTheDocument()
    expect(screen.getByText(/Last run/)).toBeInTheDocument()
    expect(await screen.findByDisplayValue('QAS')).toBeInTheDocument()
  })

  it('switches the source off through the settings', async () => {
    render(<FdaSection collectors={[row()]} />)
    const toggle = await screen.findByRole('switch', { name: 'FDA device decisions on or off' })
    await waitFor(() => expect(toggle).not.toBeDisabled())
    fireEvent.click(toggle)
    await waitFor(() => expect(api.saveFdaSettings).toHaveBeenCalledWith({ enabled: false }))
  })

  it('saves the product codes and keywords', async () => {
    render(<FdaSection collectors={[row()]} />)
    const keywords = await screen.findByLabelText('Device keywords')
    fireEvent.change(keywords, { target: { value: 'ultrasound' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save lists' }))
    await waitFor(() => expect(api.saveFdaSettings).toHaveBeenCalledWith({ productCodes: 'QAS', keywords: 'ultrasound' }))
    expect(await screen.findByText(/Saved/)).toBeInTheDocument()
  })

  it('refuses characters the server would refuse, before sending', async () => {
    render(<FdaSection collectors={[row()]} />)
    const codes = await screen.findByLabelText('Product codes')
    fireEvent.change(codes, { target: { value: 'QAS; DROP' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save lists' }))
    expect(await screen.findByText(/Product codes can only hold letters/)).toBeInTheDocument()
    expect(api.saveFdaSettings).not.toHaveBeenCalled()
  })

  it('shows a failed save in words', async () => {
    api.saveFdaSettings.mockRejectedValue(new ApiError('Spyglass could not save that.', { status: 500, kind: 'http', path: '/api/settings' }))
    render(<FdaSection collectors={[row()]} />)
    fireEvent.change(await screen.findByLabelText('Device keywords'), { target: { value: 'infusion pump' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save lists' }))
    expect(await screen.findByText('Spyglass could not save that.')).toBeInTheDocument()
  })

  it('shows a failing last run and still works when the settings cannot be read', async () => {
    api.loadFdaSettings.mockRejectedValue(new ApiError('Spyglass did not answer.', { status: 500, kind: 'http', path: '/api/settings' }))
    render(<FdaSection collectors={[row({ status: 'error', detail: 'RuntimeError: openFDA could not be read' })]} />)
    expect(await screen.findByText('Failing')).toBeInTheDocument()
    expect(await screen.findByText(/The FDA settings could not be read/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'FDA device decisions on or off' })).toBeDisabled()
  })
})
