// Tests for "Your projects" on the Profile page: the two sentences, one row per vault project, the
// 200-character line, a project that left the vault, one dirty-aware Save, and a copy without the endpoint.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/errors'
import type { ProjectRow } from '../../api/types'
import { ProjectsSection } from './ProjectsSection'
import { MAX_DESCRIPTION, sameProjects } from './projectsDraft'

const api = vi.hoisted(() => ({ loadProjects: vi.fn(), saveProjects: vi.fn() }))
vi.mock('./api', () => api)

const rows = (): ProjectRow[] => [
  { name: 'Imaging AI', description: 'Notes on AI methods for medical imaging.', in_vault: true },
  { name: 'Agent harness', description: '', in_vault: true },
  { name: 'Old prototype', description: 'Archived.', in_vault: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.loadProjects.mockResolvedValue(rows())
  api.saveProjects.mockImplementation(async (list: ProjectRow[]) => list)
})

const line = (name: string) => screen.getByLabelText(`One line about ${name}`)
const showOthers = () => fireEvent.click(screen.getByRole('button', { name: /^Show the other/ }))

describe('ProjectsSection', () => {
  it('explains what the AI sees and lists each project with its name and line', async () => {
    render(<ProjectsSection />)
    expect(await screen.findByRole('heading', { name: /Your projects/ })).toBeInTheDocument()
    expect(
      screen.getByText(/The assistant can tell you when an item could help one of these projects\. Only projects you describe here are ever mentioned to the AI, and only their name and your one line\./),
    ).toBeInTheDocument()
    expect(screen.getByText('Imaging AI')).toBeInTheDocument()
    expect(line('Imaging AI')).toHaveValue('Notes on AI methods for medical imaging.')
    showOthers()
    expect(line('Agent harness')).toHaveValue('')
    expect(line('Agent harness')).toHaveAttribute('placeholder', 'One line the AI may see. Leave empty to keep this project private.')
    expect(line('Agent harness')).toHaveAttribute('maxlength', String(MAX_DESCRIPTION))
    expect(MAX_DESCRIPTION).toBe(200)
  })

  it('keeps the name read-only', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    expect(screen.queryByDisplayValue('Imaging AI')).not.toBeInTheDocument()
  })

  it('marks a project that left the vault and lets the reader remove it', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Old prototype')
    expect(screen.getByText('no longer in your vault')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Imaging AI from the list' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Old prototype from the list' }))
    expect(screen.queryByText('Old prototype')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save projects' })).toBeEnabled()
  })

  it('enables Save only after an edit, and discards back to what is saved', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    expect(screen.getByRole('button', { name: 'Save projects' })).toBeDisabled()
    showOthers()
    fireEvent.change(line('Agent harness'), { target: { value: 'Tools for coding agents.' } })
    expect(screen.getByRole('button', { name: 'Save projects' })).toBeEnabled()
    expect(screen.getByText('You have unsaved changes to your projects.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
    expect(line('Agent harness')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Save projects' })).toBeDisabled()
  })

  it('warns before the tab is closed while there are unsaved edits, and not otherwise', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    showOthers()
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    fireEvent.change(line('Agent harness'), { target: { value: 'x' } })
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
  })

  it('saves the whole section with one button and says so', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    showOthers()
    fireEvent.change(line('Agent harness'), { target: { value: 'Tools for coding agents.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save projects' }))
    await waitFor(() => expect(api.saveProjects).toHaveBeenCalledTimes(1))
    expect(api.saveProjects.mock.calls[0][0]).toEqual([
      { name: 'Imaging AI', description: 'Notes on AI methods for medical imaging.', in_vault: true },
      { name: 'Agent harness', description: 'Tools for coding agents.', in_vault: true },
      { name: 'Old prototype', description: 'Archived.', in_vault: false },
    ])
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save projects' })).toBeDisabled()
  })

  it('shows why a save failed and keeps the edits', async () => {
    api.saveProjects.mockRejectedValue(new ApiError('Could not read the vault.', { status: 422, kind: 'http', path: '/projects', detail: 'x' }))
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    showOthers()
    fireEvent.change(line('Agent harness'), { target: { value: 'Keep me.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save projects' }))
    expect(await screen.findByText('Could not read the vault.')).toBeInTheDocument()
    expect(line('Agent harness')).toHaveValue('Keep me.')
  })

  it('says calmly that it is not available yet when the service has no projects endpoint', async () => {
    api.loadProjects.mockResolvedValue(null)
    render(<ProjectsSection />)
    expect(await screen.findByText('Projects are not available in this copy of Spyglass yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save projects' })).not.toBeInTheDocument()
  })

  it('says so when the vault has no projects', async () => {
    api.loadProjects.mockResolvedValue([])
    render(<ProjectsSection />)
    expect(await screen.findByText('No projects were found in your vault yet.')).toBeInTheDocument()
  })

  it('offers Try again when loading fails', async () => {
    api.loadProjects.mockRejectedValueOnce(new ApiError('Spyglass is not reachable.', { status: 0, kind: 'network', path: '/projects' }))
    render(<ProjectsSection />)
    expect(await screen.findByText('Spyglass is not reachable.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Imaging AI')).toBeInTheDocument()
  })
})

describe('ProjectsSection folding', () => {
  it('lists only the projects that have a line, and counts them in the heading', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    expect(screen.getByText('2 of 3 shared with the AI')).toBeInTheDocument()
    expect(screen.getByText('Old prototype')).toBeInTheDocument()
    expect(screen.queryByText('Agent harness')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show the other project' })).toBeInTheDocument()
  })

  it('shows every project on request and folds back to the shared ones', async () => {
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    showOthers()
    expect(screen.getByText('Agent harness')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show only the shared projects' }))
    expect(screen.queryByText('Agent harness')).not.toBeInTheDocument()
  })

  it('keeps a project listed while the reader types its line, even if the line is emptied again', async () => {
    api.loadProjects.mockResolvedValue([...rows(), { name: 'Garden', description: '', in_vault: true }])
    render(<ProjectsSection />)
    await screen.findByText('Imaging AI')
    showOthers()
    fireEvent.change(line('Agent harness'), { target: { value: 'Tools' } })
    expect(screen.getByText('3 of 4 shared with the AI')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show only the shared projects' }))
    expect(line('Agent harness')).toHaveValue('Tools')
    expect(screen.queryByText('Garden')).not.toBeInTheDocument()
    fireEvent.change(line('Agent harness'), { target: { value: '' } })
    expect(line('Agent harness')).toHaveValue('')
    expect(screen.getByText('2 of 4 shared with the AI')).toBeInTheDocument()
  })

  it('says the AI sees none of them when no project has a line, and still offers them all', async () => {
    api.loadProjects.mockResolvedValue(rows().map((row) => ({ ...row, description: '' })))
    render(<ProjectsSection />)
    expect(await screen.findByText('No project has a line yet, so the AI sees none of them.')).toBeInTheDocument()
    expect(screen.getByText('0 of 3 shared with the AI')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show the other 3 projects' }))
    expect(screen.queryByText('No project has a line yet, so the AI sees none of them.')).not.toBeInTheDocument()
    expect(line('Imaging AI')).toHaveValue('')
  })

  it('reports how many projects are shared, as the reader edits', async () => {
    const seen: number[] = []
    render(<ProjectsSection onSharedChange={(count) => seen.push(count)} />)
    await screen.findByText('Imaging AI')
    showOthers()
    fireEvent.change(line('Agent harness'), { target: { value: 'Tools' } })
    expect(seen[seen.length - 1]).toBe(3)
    expect(seen).toContain(2)
  })
})

describe('sameProjects', () => {
  it('compares names and lines in order', () => {
    expect(sameProjects(rows(), rows())).toBe(true)
    expect(sameProjects(rows(), rows().slice(1))).toBe(false)
    expect(sameProjects(rows(), rows().map((row) => ({ ...row, description: row.description + '!' })))).toBe(false)
  })
})
