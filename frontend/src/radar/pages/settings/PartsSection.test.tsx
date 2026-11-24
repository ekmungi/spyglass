// Tests for the Settings note that names the optional parts setup left out, and how to add them.
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PartsSection } from './PartsSection'

const api = vi.hoisted(() => ({ getCapabilities: vi.fn() }))
vi.mock('../../api/client', async (original) => ({ ...(await original<typeof import('../../api/client')>()), ...api }))

const ADD = 'To add it, open Settings > Apps > Installed apps in Windows, choose Spyglass, then Modify.'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PartsSection', () => {
  it('shows nothing when every part is installed', async () => {
    api.getCapabilities.mockResolvedValue({ pdf_reading: 'full', local_ai: true, missing: [] })
    const { container } = render(<PartsSection />)
    await vi.waitFor(() => expect(api.getCapabilities).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('names each missing part, what it changes and how to add it', async () => {
    api.getCapabilities.mockResolvedValue({
      pdf_reading: 'basic',
      local_ai: false,
      missing: [
        { id: 'pdf', name: 'PDF reading', effect: 'PDF reading is basic.', how_to_add: ADD },
        { id: 'local-ai', name: 'Local AI model', effect: 'Search by meaning is off.', how_to_add: ADD },
      ],
    })
    render(<PartsSection />)
    expect(await screen.findByRole('heading', { name: /parts not installed/i })).toBeInTheDocument()
    expect(screen.getByText('PDF reading is basic.')).toBeInTheDocument()
    expect(screen.getByText('Search by meaning is off.')).toBeInTheDocument()
    expect(screen.getAllByText(ADD)).toHaveLength(2)
  })

  it('shows nothing when the service cannot say', async () => {
    api.getCapabilities.mockRejectedValue(new Error('offline'))
    const { container } = render(<PartsSection />)
    await vi.waitFor(() => expect(api.getCapabilities).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
