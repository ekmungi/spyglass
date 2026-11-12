// Tests for the Settings "Filing" group: the three modes with their sentences, off by default,
// the quiet period, daily time and model, validation, and saving through PATCH /api/settings.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetFilingConfigured, setFilingBackgroundAvailable, setFilingConfigured } from '../../state/filingConfigured'
import { FILING_MANUAL_ONLY, FILING_NOT_SET_UP, FilingSection } from './FilingSection'
import { validateFiling } from './filingSettings'

const patchSettings = vi.fn()
vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, patchSettings: (change: Record<string, unknown>) => patchSettings(change) }
})

beforeEach(() => {
  patchSettings.mockReset()
  // The controls below belong to an install where filing is set up and background filing is available.
  setFilingConfigured(true)
  setFilingBackgroundAvailable(true)
})

afterEach(() => {
  cleanup()
  resetFilingConfigured()
})

describe('the Filing group', () => {
  it('starts off, says what each mode does, and disables the timing while off', () => {
    render(<FilingSection settings={{}} onSaved={() => undefined} />)
    expect(screen.getByLabelText(/^Off/)).toBeChecked()
    expect(screen.getByText('Only when I click File now.')).toBeInTheDocument()
    expect(screen.getByText(/may leave one question: link this to a project\?/)).toBeInTheDocument()
    expect(screen.getByText(/nothing is written until I approve the plan/)).toBeInTheDocument()
    expect(screen.getByLabelText('And once a day at')).toBeDisabled()
  })

  it('saves the mode, the quiet period, the daily time and the model', async () => {
    patchSettings.mockImplementation(async (change) => change)
    const onSaved = vi.fn()
    render(<FilingSection settings={{ radar_filing_mode: 'off' }} onSaved={onSaved} />)
    fireEvent.click(screen.getByLabelText(/^Show me the plan first/))
    fireEvent.change(screen.getByLabelText('Start after a quiet queue of (minutes)'), { target: { value: '15' } })
    fireEvent.change(screen.getByLabelText('And once a day at'), { target: { value: '20:30' } })
    fireEvent.change(screen.getByLabelText('Claude model'), { target: { value: 'haiku' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save filing settings' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(patchSettings).toHaveBeenCalledWith({ radar_filing_mode: 'plan_first', radar_filing_quiet_minutes: 15, radar_filing_daily_time: '20:30', radar_filing_model: 'haiku' })
    expect(await screen.findByText('Saved. The next check uses these settings.')).toBeInTheDocument()
  })

  it('refuses a quiet period out of range without saving', () => {
    render(<FilingSection settings={{ radar_filing_mode: 'auto' }} onSaved={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Start after a quiet queue of (minutes)'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save filing settings' }))
    expect(screen.getByText('Use a whole number of minutes from 2 to 240.')).toBeInTheDocument()
    expect(patchSettings).not.toHaveBeenCalled()
  })

  it('validates the daily time', () => {
    expect(validateFiling({ mode: 'auto', quiet: '10', daily: '25:00', model: 'sonnet' }).daily).toBe('Use a time like 21:00.')
    expect(validateFiling({ mode: 'auto', quiet: '10', daily: '21:00', model: 'sonnet' })).toEqual({})
  })
})

describe('the Filing group where background filing is not available', () => {
  it('shows one paragraph and no mode, quiet period, daily time or model', () => {
    setFilingBackgroundAvailable(false)
    render(<FilingSection settings={{ radar_filing_mode: 'auto' }} onSaved={() => undefined} />)
    expect(screen.getByRole('heading', { name: 'Filing' })).toBeInTheDocument()
    expect(screen.getByText(FILING_MANUAL_ONLY)).toBeInTheDocument()
    expect(FILING_MANUAL_ONLY).toBe(
      'Filing runs when you click File now, in one Claude Code session that you watch and approve. Background filing is not available in this version.',
    )
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Start after a quiet queue of (minutes)')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('And once a day at')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Claude model')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save filing settings' })).not.toBeInTheDocument()
  })

  it('counts a service reply without the field as not available', () => {
    resetFilingConfigured()
    setFilingConfigured(true)
    render(<FilingSection settings={{}} onSaved={() => undefined} />)
    expect(screen.getByText(FILING_MANUAL_ONLY)).toBeInTheDocument()
  })
})

describe('the Filing group where filing is not set up', () => {
  it('keeps the heading and shows one explanation in place of the controls', () => {
    setFilingConfigured(false)
    render(<FilingSection settings={{}} onSaved={() => undefined} />)
    expect(screen.getByRole('heading', { name: 'Filing' })).toBeInTheDocument()
    expect(screen.getByText(FILING_NOT_SET_UP)).toBeInTheDocument()
    expect(FILING_NOT_SET_UP).toBe(
      "Filing into a notes vault is an optional integration. It hands the items you choose to your own Claude Code filing skills, which must be named in Spyglass's settings file. See the user guide.",
    )
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save filing settings' })).not.toBeInTheDocument()
  })

  it('shows the same explanation while the answer is not known yet', () => {
    resetFilingConfigured()
    render(<FilingSection settings={{}} onSaved={() => undefined} />)
    expect(screen.getByText(FILING_NOT_SET_UP)).toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })
})
