// Tests for the Settings section "Spyglass on this computer": start with Windows and Quit.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import { DesktopSection } from './DesktopSection'

const api = vi.hoisted(() => ({
  getAutostart: vi.fn(),
  setAutostart: vi.fn(),
  quitSpyglass: vi.fn(),
}))
const toasts = vi.hoisted(() => vi.fn())
vi.mock('../../api/client', async (original) => ({ ...(await original<typeof import('../../api/client')>()), ...api }))
vi.mock('../../ui', async (original) => ({ ...(await original<typeof import('../../ui')>()), toast: toasts }))

beforeEach(() => {
  vi.clearAllMocks()
  api.getAutostart.mockResolvedValue({ available: true, enabled: false })
  api.setAutostart.mockResolvedValue({ available: true, enabled: true })
  api.quitSpyglass.mockResolvedValue(null)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('DesktopSection', () => {
  it('hides the Start with Windows switch when it is not available', async () => {
    api.getAutostart.mockResolvedValue({ available: false, enabled: false })
    render(<DesktopSection />)
    expect(screen.getByRole('heading', { name: 'Spyglass on this computer' })).toBeInTheDocument()
    await screen.findByRole('button', { name: 'Quit Spyglass' })
    await waitFor(() => expect(api.getAutostart).toHaveBeenCalled())
    expect(screen.queryByRole('switch', { name: 'Start with Windows' })).toBeNull()
  })

  it('turns Start with Windows on through the API', async () => {
    render(<DesktopSection />)
    const toggle = await screen.findByRole('switch', { name: 'Start with Windows' })
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(toggle)
    await waitFor(() => expect(api.setAutostart).toHaveBeenCalledWith(true))
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Start with Windows' })).toHaveAttribute('aria-checked', 'true'))
  })

  it('leaves the switch as it was and says why when Windows refuses the change', async () => {
    api.setAutostart.mockRejectedValueOnce(new ApiError('Windows did not allow this change.', { status: 503, kind: 'http', path: '/desktop/autostart' }))
    render(<DesktopSection />)
    fireEvent.click(await screen.findByRole('switch', { name: 'Start with Windows' }))
    await waitFor(() => expect(toasts).toHaveBeenCalledWith('Windows did not allow this change.', { tone: 'error' }))
    expect(screen.getByRole('switch', { name: 'Start with Windows' })).toHaveAttribute('aria-checked', 'false')
  })

  it('quits Spyglass and says how to open it again', async () => {
    render(<DesktopSection />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quit Spyglass' }))
    expect(await screen.findByText('Spyglass has stopped. Open it again from the Start menu.')).toBeInTheDocument()
    expect(api.quitSpyglass).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Quit Spyglass' })).toBeNull()
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('keeps the page as it was and says why when Quit does not go through', async () => {
    api.quitSpyglass.mockRejectedValueOnce(new ApiError('Spyglass refused this request.', { status: 403, kind: 'http', path: '/api/shutdown' }))
    render(<DesktopSection />)
    fireEvent.click(await screen.findByRole('button', { name: 'Quit Spyglass' }))
    await waitFor(() => expect(toasts).toHaveBeenCalledWith('Spyglass refused this request.', { tone: 'error' }))
    expect(screen.queryByText(/Spyglass has stopped/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Quit Spyglass' })).toBeEnabled()
  })
})
