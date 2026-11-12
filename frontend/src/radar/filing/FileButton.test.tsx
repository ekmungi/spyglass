// Tests for the reader's File in vault control: one click queues the item (nothing opens), the
// "File as…" dialog sends the kind, project and note, a queued item reads "Waiting to be filed" with
// Remove and Change, and a filed item reads "Filed". The sample service stands in for the real one.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { getClaudeDialog } from '../claude/claudeStore'
import { mockFetch, resetMockState } from '../mock'
import { QUEUED_TOAST, resetFilingState } from '../state/filingState'
import { subscribeToasts, type ToastMessage } from '../ui/toastStore'
import { FileButton } from './FileButton'

let calls: { method: string; path: string; body: unknown }[] = []
// Requests still on their way to the sample service. A test ends before a slow one (140-300ms) may
// land, which would then change the next test's queue, so each test waits for its own to settle.
let inFlight: Promise<Response>[] = []
let toasts: readonly ToastMessage[] = []
let unsubscribe: () => void

beforeEach(() => {
  resetMockState()
  resetFilingState()
  calls = []
  inFlight = []
  setFetchForTesting(async (url, init) => {
    const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined
    calls.push({ method: (init?.method ?? 'GET').toUpperCase(), path: new URL(url, 'http://x').pathname.replace('/api/radar', ''), body })
    const response = mockFetch(url, init)
    inFlight.push(response)
    return response
  })
  unsubscribe = subscribeToasts((list) => {
    toasts = list
  })
})

afterEach(async () => {
  unsubscribe()
  cleanup()
  await Promise.allSettled(inFlight)
  setFetchForTesting(null)
})

const writes = () => calls.filter((call) => call.method !== 'GET')

describe('one click', () => {
  it('queues the item with kind resource and no project, opens nothing, and offers Undo', async () => {
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'File in vault' }))
    expect(await screen.findByRole('button', { name: 'Waiting to be filed' })).toBeInTheDocument()
    expect(writes()).toEqual([{ method: 'POST', path: '/items/101/file', body: {} }])
    expect(getClaudeDialog()).toBeNull()
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(QUEUED_TOAST))
    expect(QUEUED_TOAST).toBe('Added to the filing queue')
  })

  it('takes the item out again when Undo is chosen', async () => {
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'File in vault' }))
    await screen.findByRole('button', { name: 'Waiting to be filed' })
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(QUEUED_TOAST))
    const toast = toasts.find((entry) => entry.message === QUEUED_TOAST)
    await act(async () => toast?.action?.onClick())
    expect(await screen.findByRole('button', { name: 'File in vault' })).toBeInTheDocument()
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(['POST /items/101/file', 'DELETE /items/101/file'])
  })

  it('goes back to "File in vault" and says so when the service refuses', async () => {
    setFetchForTesting(async () => new Response(JSON.stringify({ detail: 'This item is already filed.' }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'File in vault' }))
    await waitFor(() => expect(toasts.some((entry) => entry.tone === 'error')).toBe(true))
    expect(screen.getByRole('button', { name: 'File in vault' })).toBeInTheDocument()
  })
})

describe('File as…', () => {
  it('sends the kind, the project and the note, and Enter confirms', async () => {
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'More ways to file' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'File as…' }))
    await screen.findByRole('dialog', { name: 'File as…' })
    const kind = screen.getByLabelText('File it as') as HTMLSelectElement
    expect(Array.from(kind.options).map((option) => option.text)).toEqual(['Resource', 'To explore', 'Learning', 'Feature idea'])
    await waitFor(() => expect(screen.getByRole('option', { name: 'Imaging AI' })).toBeInTheDocument())
    fireEvent.change(kind, { target: { value: 'feature idea' } })
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'Imaging AI' } })
    const note = screen.getByLabelText(/Note for the filing session/)
    fireEvent.change(note, { target: { value: '  try it for triage  ' } })
    fireEvent.keyDown(note, { key: 'Enter' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(writes()).toEqual([{ method: 'POST', path: '/items/101/file', body: { kind: 'feature idea', project: 'Imaging AI', note: 'try it for triage' } }]))
    expect(await screen.findByRole('button', { name: 'Waiting to be filed' })).toBeInTheDocument()
  })

  it('offers only projects that are in the vault, plus "No project"', async () => {
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'More ways to file' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'File as…' }))
    await waitFor(() => expect(screen.getByRole('option', { name: 'Regulation notes' })).toBeInTheDocument())
    const options = Array.from((screen.getByLabelText('Project') as HTMLSelectElement).options).map((option) => option.text)
    expect(options).toEqual(['No project', 'Imaging AI', 'Agent harness', 'Regulation notes'])
  })

  it('Cancel closes without queuing', async () => {
    render(<FileButton itemId={101} filing={null} filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'More ways to file' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'File as…' }))
    await screen.findByRole('dialog', { name: 'File as…' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(writes()).toEqual([])
  })
})

describe('waiting and filed', () => {
  it('a queued item offers Remove from the queue and Change…', async () => {
    render(<FileButton itemId={101} filing="waiting" filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'Waiting to be filed' }))
    expect(screen.getByRole('menuitem', { name: 'Remove from the queue' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Change…' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove from the queue' }))
    expect(await screen.findByRole('button', { name: 'File in vault' })).toBeInTheDocument()
    expect(writes()).toEqual([{ method: 'DELETE', path: '/items/101/file', body: undefined }])
  })

  it('Change… starts from the stored choices and saves them again', async () => {
    await mockFetch('/api/radar/items/101/file', { method: 'POST', body: JSON.stringify({ kind: 'learning', note: 'for Friday' }) })
    render(<FileButton itemId={101} filing="waiting" filed={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'Waiting to be filed' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Change…' }))
    await screen.findByRole('dialog', { name: 'Change how this is filed' })
    await waitFor(() => expect((screen.getByLabelText('File it as') as HTMLSelectElement).value).toBe('learning'))
    expect((screen.getByLabelText(/Note for the filing session/) as HTMLInputElement).value).toBe('for Friday')
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(writes()).toEqual([{ method: 'POST', path: '/items/101/file', body: { kind: 'learning', note: 'for Friday' } }]))
  })

  it('an item that is already filed shows "Filed" and cannot be queued', () => {
    render(<FileButton itemId={101} filing={null} filed={{ path: 'Inbox/Note.md', project: 'Imaging AI', at: '2026-11-12T08:00:00Z' }} />)
    expect(screen.getByRole('button', { name: /Filed/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'File in vault' })).not.toBeInTheDocument()
  })
})
