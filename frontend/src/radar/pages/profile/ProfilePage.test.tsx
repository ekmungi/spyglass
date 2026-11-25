// Tests for the Profile page: rendering, editing, the unsaved-changes guard, validation, saving and errors.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const tab = (name: string | RegExp) => screen.getByRole('tab', { name })
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
    fireEvent.click(tab(/^Topics/))
    fireEvent.change(screen.getByLabelText('New topic'), { target: { value: 'Surgical robots' } })
    fireEvent.change(screen.getByLabelText('Section for the new topic'), { target: { value: 'health' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add topic' }))
    expect(screen.getByLabelText('Topic 3')).toHaveValue('Surgical robots')

    fireEvent.change(screen.getByLabelText('New topic'), { target: { value: 'surgical robots' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add topic' }))
    expect(screen.getByText('This topic is already in the list.')).toBeInTheDocument()

    fireEvent.click(tab(/^Leave out/))
    fireEvent.change(screen.getByLabelText('New subject to leave out'), { target: { value: 'Crypto prices' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(screen.getByLabelText('Leave out 3')).toHaveValue('Crypto prices')

    fireEvent.click(tab(/^Topics/))
    fireEvent.click(screen.getByRole('button', { name: 'Remove topic AI in medical imaging' }))
    expect(screen.queryByDisplayValue('AI in medical imaging')).not.toBeInTheDocument()
    fireEvent.click(tab(/^Leave out/))
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

const FIVE_PROJECTS = [
  { name: 'Imaging AI', description: 'Notes on AI methods for medical imaging.', in_vault: true },
  { name: 'Agent harness', description: 'Tools for coding agents.', in_vault: true },
  { name: 'Garden', description: '', in_vault: true },
  { name: 'Taxes', description: '', in_vault: true },
  { name: 'Reading list', description: '', in_vault: true },
]

describe('ProfilePage tabs', () => {
  it('shows one strip with a tab for each part of the profile, with counts on Topics and Your projects', async () => {
    api.loadProjects.mockResolvedValue(FIVE_PROJECTS)
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    await waitFor(() => expect(tab(/^Your projects/)).toHaveTextContent('2 shared'))
    const strip = screen.getByRole('tablist', { name: 'Profile' })
    const labels = within(strip)
      .getAllByRole('tab')
      .map((entry) => entry.textContent)
    expect(labels).toEqual(['About you', 'Sections', 'Topics 2', 'Your projects 2 shared', 'Leave out', 'Learned'])
    expect(tab('About you')).toHaveAttribute('aria-selected', 'true')
  })

  it('shows only the selected part, and keeps the page-wide Save bar on every tab', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    expect(statementBox()).toBeVisible()
    expect(screen.getByLabelText('Topic 1')).not.toBeVisible()
    for (const name of ['About you', 'Sections', 'Topics', 'Your projects', 'Leave out', 'Learned']) {
      fireEvent.click(tab(new RegExp(`^${name}`)))
      expect(screen.getByRole('button', { name: 'Save profile' })).toBeVisible()
      expect(screen.getByRole('button', { name: 'Discard changes' })).toBeVisible()
    }
    expect(screen.getByText('A paper about polyp detection')).toBeVisible()
    expect(statementBox()).not.toBeVisible()
  })

  it('keeps text typed under About you when the reader visits another tab, and saves it from there', async () => {
    api.saveProfile.mockResolvedValue(reply(4))
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Typed under About you.' } })
    fireEvent.click(tab(/^Topics/))
    fireEvent.change(screen.getByLabelText('Topic 1'), { target: { value: 'Imaging, renamed' } })
    fireEvent.click(tab('About you'))
    expect(statementBox()).toHaveValue('Typed under About you.')
    fireEvent.click(tab(/^Topics/))
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(api.saveProfile).toHaveBeenCalledTimes(1))
    expect(api.saveProfile.mock.calls[0][0].statement).toBe('Typed under About you.')
    expect(api.saveProfile.mock.calls[0][0].topics[0].name).toBe('Imaging, renamed')
  })

  it('opens the first tab that holds a problem when a save is refused', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: '   ' } })
    fireEvent.click(tab(/^Leave out/))
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/Describe who you are/)).toBeVisible()
    expect(tab('About you')).toHaveAttribute('aria-selected', 'true')
    expect(api.saveProfile).not.toHaveBeenCalled()
  })

  it('keeps the unsaved projects lines when the reader moves between tabs, and counts only the saved ones', async () => {
    api.loadProjects.mockResolvedValue(FIVE_PROJECTS)
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.click(tab(/^Your projects/))
    fireEvent.click(await screen.findByRole('button', { name: 'Show the other 3 projects' }))
    fireEvent.change(screen.getByLabelText('One line about Garden'), { target: { value: 'My vegetable beds.' } })
    fireEvent.click(tab(/^Topics/))
    fireEvent.click(tab(/^Your projects/))
    expect(screen.getByLabelText('One line about Garden')).toHaveValue('My vegetable beds.')
    // The assistant still sees two projects until the line is saved.
    expect(tab(/^Your projects/)).toHaveTextContent('2 shared')
    expect(screen.getByText('2 of 5 shared with the AI')).toBeVisible()
  })

  it('lists only the projects that have a line, and offers the others on request', async () => {
    api.loadProjects.mockResolvedValue(FIVE_PROJECTS)
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.click(tab(/^Your projects/))
    expect(await screen.findByText('2 of 5 shared with the AI')).toBeVisible()
    expect(screen.getByLabelText('One line about Imaging AI')).toBeVisible()
    expect(screen.queryByLabelText('One line about Garden')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show the other 3 projects' }))
    expect(screen.getByLabelText('One line about Garden')).toBeVisible()
    expect(screen.getByLabelText('One line about Reading list')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Show only the shared projects' }))
    expect(screen.queryByLabelText('One line about Garden')).not.toBeInTheDocument()
  })

  it('says so when no project has a line yet', async () => {
    api.loadProjects.mockResolvedValue(FIVE_PROJECTS.map((row) => ({ ...row, description: '' })))
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.click(tab(/^Your projects/))
    expect(await screen.findByText('No project has a line yet, so the AI sees none of them.')).toBeVisible()
    expect(screen.getByText('0 of 5 shared with the AI')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Show the other 5 projects' })).toBeVisible()
  })
})

describe('ProfilePage projects and the one Save bar', () => {
  /** Open Your projects, list every project and write a line about Garden. */
  async function writeGardenLine() {
    fireEvent.click(tab(/^Your projects/))
    fireEvent.click(await screen.findByRole('button', { name: 'Show the other 3 projects' }))
    fireEvent.change(screen.getByLabelText('One line about Garden'), { target: { value: 'My vegetable beds.' } })
  }

  beforeEach(() => {
    api.loadProjects.mockResolvedValue(FIVE_PROJECTS)
    api.saveProjects.mockImplementation(async (rows: unknown) => rows)
  })

  it('has one Save bar on the Your projects tab, with no separate Save for the projects', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.click(tab(/^Your projects/))
    await screen.findByText('2 of 5 shared with the AI')
    expect(screen.queryByRole('button', { name: 'Save projects' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Discard changes' })).toHaveLength(1)
  })

  it('saves a projects line typed on its tab when Save profile is pressed on another tab', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    await writeGardenLine()
    fireEvent.click(tab(/^Topics/))
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
    expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(api.saveProjects).toHaveBeenCalledTimes(1))
    expect(api.saveProjects.mock.calls[0][0]).toContainEqual({ name: 'Garden', description: 'My vegetable beds.', in_vault: true })
    // The profile itself did not change, so it is not sent again.
    expect(api.saveProfile).not.toHaveBeenCalled()
    expect(await screen.findByText(/^Saved\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('changes the counts only after the save, not while the reader types', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    await writeGardenLine()
    expect(tab(/^Your projects/)).toHaveTextContent('2 shared')
    expect(screen.getByText('2 of 5 shared with the AI')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(tab(/^Your projects/)).toHaveTextContent('3 shared'))
    expect(screen.getByText('3 of 5 shared with the AI')).toBeVisible()
  })

  it('discards the projects lines together with the profile edits', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Changed.' } })
    await writeGardenLine()
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
    expect(screen.getByLabelText('One line about Garden')).toHaveValue('')
    fireEvent.click(tab('About you'))
    expect(statementBox()).toHaveValue('Someone who follows AI closely and builds with AI agents, and wants a short daily picture of AI and the fields they care about.')
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled()
  })

  it('says the projects were not saved when only their save fails, and keeps them changed', async () => {
    api.saveProfile.mockResolvedValue({ ...reply(4), profile: { ...reply(4).profile, statement: 'New statement.' } })
    api.saveProjects.mockRejectedValue(new ApiError('Could not read the vault.', { status: 422, kind: 'http', path: '/projects' }))
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'New statement.' } })
    await writeGardenLine()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/Your projects were not saved\. Could not read the vault\./)).toBeInTheDocument()
    expect(screen.getByText(/Your profile was saved\./)).toBeInTheDocument()
    expect(api.saveProfile).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText('One line about Garden')).toHaveValue('My vegetable beds.')
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
  })

  it('says the profile was not saved when only its save fails, and keeps it changed', async () => {
    api.saveProfile.mockRejectedValue(new ApiError('The profile could not be stored.', { status: 500, kind: 'http', path: '/profile' }))
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    fireEvent.change(statementBox(), { target: { value: 'Kept.' } })
    await writeGardenLine()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    expect(await screen.findByText(/Your profile was not saved\. The profile could not be stored\./)).toBeInTheDocument()
    expect(screen.getByText(/Your projects were saved\./)).toBeInTheDocument()
    await waitFor(() => expect(tab(/^Your projects/)).toHaveTextContent('3 shared'))
    fireEvent.click(tab('About you'))
    expect(statementBox()).toHaveValue('Kept.')
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled()
  })

  it('warns before the tab is closed while only a projects line is unsaved', async () => {
    render(<ProfilePage />)
    await screen.findByText(/Spyglass judges/)
    await screen.findByText('2 of 5 shared with the AI')
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    await writeGardenLine()
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
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
