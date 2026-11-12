// Tests for "Open in Claude Code": the two choices and their defaults, the exact text shown (refreshed
// after a 300 ms pause), the unavailable and failing states, and the call that opens Claude Code with
// the same body the preview showed. Filing is the To file queue, so there is no filing choice here.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import type { ClaudePreview } from '../api/types'
import { subscribeToasts, type ToastMessage } from '../ui/toastStore'
import { ClaudeDialogHost } from './ClaudeDialogHost'
import { closeClaudeDialog, getClaudeDialog, openClaudeDialog, startingIntent } from './claudeStore'
import { OPENED_TOAST } from './ClaudeCodeDialog'
import { buildClaudeRequest } from './request'

const api = vi.hoisted(() => ({ previewClaude: vi.fn(), openInClaude: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const preview = (over: Partial<ClaudePreview> = {}): ClaudePreview => ({
  text: 'Please file this item.',
  vault: 'C:/Vault',
  available: true,
  reason: null,
  ...over,
})

let toasts: readonly ToastMessage[] = []
let unsubscribe: () => void

beforeEach(() => {
  vi.clearAllMocks()
  api.previewClaude.mockResolvedValue(preview())
  api.openInClaude.mockResolvedValue({ opened: true })
  unsubscribe = subscribeToasts((list) => {
    toasts = list
  })
})

afterEach(() => {
  unsubscribe()
  act(() => closeClaudeDialog())
  cleanup()
})

/** Open the dialog for item 7 and wait for its first preview. */
async function openDialog(intent?: 'discuss' | 'custom') {
  render(<ClaudeDialogHost />)
  act(() => openClaudeDialog({ itemId: 7, intent }))
  await screen.findByRole('dialog', { name: 'Open in Claude Code' })
  await waitFor(() => expect(screen.getByLabelText('Exactly what will be sent')).toHaveValue('Please file this item.'))
}

describe('the choices', () => {
  it('says what it does and offers two choices, "Discuss this item" first, and no filing choice', async () => {
    await openDialog()
    expect(screen.getByText('Claude Code opens in your notes vault with this item. You see and approve everything it does there.')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Discuss this item/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /My own request/ })).not.toBeChecked()
    expect(screen.queryByRole('radio', { name: /File into a project/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Project')).not.toBeInTheDocument()
    expect(api.previewClaude).toHaveBeenCalledWith(7, { intent: 'discuss' }, expect.anything())
  })

  it('starts where the opener asked', async () => {
    await openDialog('custom')
    expect(screen.getByRole('radio', { name: /My own request/ })).toBeChecked()
  })

  it('knows the starting choice and builds only the fields that belong to the choice', () => {
    expect(startingIntent({})).toBe('discuss')
    expect(startingIntent({ intent: 'custom' })).toBe('custom')
    expect(buildClaudeRequest({ intent: 'discuss', custom: 'x' })).toEqual({ intent: 'discuss' })
    expect(buildClaudeRequest({ intent: 'custom', custom: 'Compare it' })).toEqual({ intent: 'custom', custom: 'Compare it' })
  })
})

describe('my own request', () => {
  it('shows a text area, and cannot open until something is written', async () => {
    await openDialog('custom')
    expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Your request'), { target: { value: 'Compare it with my notes' } })
    await waitFor(() => expect(api.previewClaude).toHaveBeenLastCalledWith(7, { intent: 'custom', custom: 'Compare it with my notes' }, expect.anything()))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeEnabled())
  })
})

describe('the text that will be sent', () => {
  it('shows the service text read-only, in a box with that title, and the vault it opens in', async () => {
    api.previewClaude.mockResolvedValue(preview({ text: 'Exactly this text.' }))
    render(<ClaudeDialogHost />)
    act(() => openClaudeDialog({ itemId: 7 }))
    const box = await screen.findByDisplayValue('Exactly this text.')
    expect(box).toHaveAttribute('readonly')
    expect(screen.getByLabelText('Exactly what will be sent')).toBe(box)
    expect(screen.getByText('Opens in C:/Vault')).toBeInTheDocument()
  })

  it('waits 300 ms after a change before asking again', async () => {
    await openDialog('custom')
    expect(api.previewClaude).toHaveBeenCalledTimes(1)
    const field = screen.getByLabelText('Your request')
    fireEvent.change(field, { target: { value: 'a' } })
    fireEvent.change(field, { target: { value: 'ab' } })
    fireEvent.change(field, { target: { value: 'abc' } })
    // Nothing yet: the pause has not run out.
    expect(api.previewClaude).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(api.previewClaude).toHaveBeenCalledTimes(2))
    expect(api.previewClaude).toHaveBeenLastCalledWith(7, { intent: 'custom', custom: 'abc' }, expect.anything())
  })

  it('keeps Open disabled while the text is being prepared', async () => {
    await openDialog('custom')
    fireEvent.change(screen.getByLabelText('Your request'), { target: { value: 'x' } })
    expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeEnabled())
  })
})

describe('when Claude Code cannot be opened', () => {
  it('disables Open and says why in plain words', async () => {
    api.previewClaude.mockResolvedValue(preview({ available: false, reason: 'Claude Code is not installed on this computer.' }))
    render(<ClaudeDialogHost />)
    act(() => openClaudeDialog({ itemId: 7 }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Claude Code is not installed on this computer.')
    expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeDisabled()
  })

  it('says calmly that it is not in this copy yet when the service has no such endpoint', async () => {
    api.previewClaude.mockRejectedValue(new ApiError('That item or page no longer exists.', { status: 404, kind: 'http', path: '/items/7/claude/preview' }))
    render(<ClaudeDialogHost />)
    act(() => openClaudeDialog({ itemId: 7 }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not available in this copy of Spyglass yet')
    expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeDisabled()
  })

  it('shows the readable reason when opening fails, and stays open', async () => {
    api.openInClaude.mockRejectedValue(new ApiError('Claude Code could not be started: the command was not found.', { status: 422, kind: 'http', path: '/x', detail: 'x' }))
    await openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Open Claude Code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('the command was not found')
    expect(screen.getByRole('dialog', { name: 'Open in Claude Code' })).toBeInTheDocument()
    expect(getClaudeDialog()).not.toBeNull()
  })
})

describe('opening', () => {
  it('sends the same body the preview used, tells the reader to finish there, and closes', async () => {
    await openDialog('custom')
    fireEvent.change(screen.getByLabelText('Your request'), { target: { value: 'Compare it' } })
    await waitFor(() => expect(api.previewClaude).toHaveBeenLastCalledWith(7, { intent: 'custom', custom: 'Compare it' }, expect.anything()))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open Claude Code' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Open Claude Code' }))
    await waitFor(() => expect(api.openInClaude).toHaveBeenCalledWith(7, { intent: 'custom', custom: 'Compare it' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(toasts.map((entry) => entry.message)).toContain(OPENED_TOAST)
    expect(OPENED_TOAST).toBe('Claude Code is opening. Finish there; Spyglass shows where it was filed when Claude reports back.')
  })

  it('closes with Cancel without opening anything', async () => {
    await openDialog()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.openInClaude).not.toHaveBeenCalled()
  })

  it('starts fresh each time it is opened', async () => {
    await openDialog()
    fireEvent.click(screen.getByRole('radio', { name: /My own request/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    act(() => openClaudeDialog({ itemId: 7 }))
    expect(await screen.findByRole('radio', { name: /Discuss this item/ })).toBeChecked()
  })
})
