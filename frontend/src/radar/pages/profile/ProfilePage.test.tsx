// Tests for the Profile page: rendering, editing, the unsaved-changes guard, validation, saving and errors.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import ProfilePage from '../ProfilePage'
import { parseProfileReply, type ProfileReply } from './api'
import { forgetDraft } from './draftMemory'
import { countErrors, validateProfile } from './validate'

const api = vi.hoisted(() => ({ loadProfile: vi.fn(), saveProfile: vi.fn(), loadProjects: vi.fn(), saveProjects: vi.fn() }))
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), ...api }))

function reply(version = 3): ProfileReply {
  return {
    profile: {
      version,
      statement: 'Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.',
      sections: [
        { key: 'models', label: 'Models', description: 'New model releases.' },
        { key: 'health', label: 'Health', description: 'Healthcare AI.' },
      ],
      topics: [
        { name: 'AI in medical imaging', section: 'health' },
        { name: 'Open-weight models', section: 'models' },
      ],
      avoid: ['Sports', 'Celebrity news'],
    },
    examples: { liked: ['A paper about polyp detection'], disliked: ['Ten gadget deals this week'] },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  forgetDraft()
  api.loadProfile.mockResolvedValue(reply())
  api.loadProjects.mockResolvedValue(null)
})

const statementBox = () => screen.getByLabelText('Who you are and what you need to know')

describe('ProfilePage', () => {
  it('explains the profile and shows every part of it, with what Spyglass has learned', async () => {
    render(<ProfilePage />)
    expect(await screen.findByText(/Spyglass judges every item it collects against this profile/)).toBeInTheDocument()
    expect(statementBox()).toHaveValue('Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.')
    expect(screen.queryByText(/key: models/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('Topic 1')).toHaveValue('AI in medical imaging')
    expect(screen.getByLabelText('Leave out 2')).toHaveValue('Celebrity news')
    expect(screen.getByText('A paper about polyp detection')).toBeInTheDocument()
    expect(screen.getByText('Ten gadget deals this week')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('enables saving once something changes, and discards back to the saved profile', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Changed.' } })
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
    expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
    expect(statementBox()).toHaveValue('Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.')
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('refuses to save an empty statement or an empty topic and says what to fix', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: '   ' } })
    fireEvent.change(screen.getByLabelText('Topic 2'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/Describe who you are/)).toBeInTheDocument()
    expect(screen.getByText('Give this topic a name, or remove it.')).toBeInTheDocument()
    expect(screen.getByText('2 things need fixing before you can save.')).toBeInTheDocument()
    expect(statementBox()).toHaveAttribute('aria-invalid', 'true')
    expect(api.saveProfile).not.toHaveBeenCalled()
  })

  it('saves the edited profile and confirms it', async () => {
    api.saveProfile.mockResolvedValue({ ...reply(4), profile: { ...reply(4).profile, statement: 'New statement.' } })
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: '  New statement.  ' } })
    fireEvent.change(screen.getAllByLabelText(/Section name/)[0], { target: { value: 'Model releases' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledTimes(1))
    const sent = api.saveProfile.mock.calls[0][0]
    expect(sent.statement).toBe('New statement.')
    expect(sent.sections[0]).toMatchObject({ key: 'models', label: 'Model releases' })
    expect(sent.version).toBe(3)
    expect(await screen.findByText('Saved. Changes apply to items collected from now on.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('adds a topic and an avoid line, refuses duplicates, and removes entries', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(screen.getByLabelText('New topic'), { target: { value: 'Surgical robots' } })
    fireEvent.change(screen.getByLabelText('Section for the new topic'), { target: { value: 'health' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add topic' }))
    expect(screen.getByLabelText('Topic 3')).toHaveValue('Surgical robots')

    fireEvent.change(screen.getByLabelText('New topic'), { target: { value: 'surgical robots' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add topic' }))
    expect(screen.getByText('This topic is already in the list.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('New subject to leave out'), { target: { value: 'Crypto prices' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(screen.getByLabelText('Leave out 3')).toHaveValue('Crypto prices')

    fireEvent.click(screen.getByRole('button', { name: 'Remove topic AI in medical imaging' }))
    expect(screen.queryByDisplayValue('AI in medical imaging')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Sports from the leave-out list' }))
    expect(screen.queryByDisplayValue('Sports')).not.toBeInTheDocument()
  })

  it('shows the server message when saving fails and keeps the edits', async () => {
    api.saveProfile.mockRejectedValue(new ApiError('topics.0.name: String should have at most 200 characters', { status: 422, kind: 'http', path: '/profile' }))
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Edited.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/String should have at most 200 characters/)).toBeInTheDocument()
    expect(statementBox()).toHaveValue('Edited.')
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
  })

  it('keeps unsaved edits when the reader leaves the page and returns', async () => {
    const first = render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Half-finished edit' } })
    first.unmount()
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    expect(statementBox()).toHaveValue('Half-finished edit')
    expect(screen.getByText(/Your unsaved edits from earlier are back/)).toBeInTheDocument()
  })

  it('shows an error with a retry when the profile cannot be loaded', async () => {
    api.loadProfile.mockRejectedValueOnce(new ApiError('Spyglass is not reachable. Check that the service is running, then try again.', { status: 0, kind: 'network', path: '/profile' }))
    render(<ProfilePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Spyglass is not reachable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/Spyglass judges/)).toBeInTheDocument()
  })

  it('does not show the internal key of a section, and offers no way to edit it', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    expect(screen.queryByText(/key:/)).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('health')).not.toBeInTheDocument()
  })
})

describe('profile helpers', () => {
  it('reads a bare profile and a wrapped one', () => {
    const bare = parseProfileReply({ version: 2, statement: 's', sections: [], topics: [], avoid: [] })
    expect(bare.profile.version).toBe(2)
    expect(bare.examples).toEqual({ liked: [], disliked: [] })
    const wrapped = parseProfileReply({ profile: { version: 5, statement: 'x' }, examples: { liked: ['a', 7], disliked: ['b'] } })
    expect(wrapped.profile).toMatchObject({ version: 5, sections: [], topics: [], avoid: [] })
    expect(wrapped.examples).toEqual({ liked: ['a'], disliked: ['b'] })
  })

  it('counts validation problems, including duplicates and unknown sections', () => {
    const good = reply().profile
    expect(countErrors(validateProfile(good))).toBe(0)
    const bad = validateProfile({
      ...good,
      topics: [{ name: 'A', section: 'nope' }, { name: 'a', section: '' }],
      avoid: ['x', 'X', ''],
    })
    expect(bad.topics[0].section).toBeDefined()
    expect(bad.topics[1].name).toBe('This topic is already in the list.')
    expect(bad.avoid[1]).toBeDefined()
    expect(bad.avoid[2]).toBeDefined()
  })
})
