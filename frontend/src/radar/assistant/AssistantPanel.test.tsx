// Tests for the assistant panel: no-engine empty state, a passage sent from the selection
// toolbar, and an error mid-answer shown inline with Retry.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { navigate } from '../router'
import { AssistantPanel } from './AssistantPanel'
import { queueSend, setAssistTarget } from './assistStore'
import { resetConversations } from './useThread'

beforeEach(() => {
  resetMockState()
  resetConversations()
  clearResourceCache()
  window.localStorage.clear()
  setAssistTarget({ kind: 'item', id: 101, title: 'Sample' })
})

afterEach(() => {
  cleanup()
  setFetchForTesting(null)
  setAssistTarget(null)
})

describe('AssistantPanel', () => {
  it('points to Settings when no engine is available', async () => {
    setFetchForTesting(async (url, init) => {
      if (url.endsWith('/engines')) return new Response(JSON.stringify([{ id: 'x', label: 'X', kind: 'api', available: false, reason: 'No key', models: [], default_model: null }]), { status: 200 })
      return mockFetch(url, init)
    })
    render(<AssistantPanel surface="reader" />)
    expect(await screen.findByText('No assistant is set up yet', {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Settings' })).toBeInTheDocument()
  })

  it('sends a passage queued by the selection toolbar, showing it as a quote', async () => {
    setFetchForTesting(mockFetch)
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: 'Explain' }, { timeout: 4000 })
    act(() => queueSend('reader', { content: 'Why is this so?', selection: 'flat-rate pricing for long inputs' }))
    const panel = screen.getByRole('complementary', { name: 'Assistant' })
    expect(await within(panel).findByText('flat-rate pricing for long inputs')).toBeInTheDocument()
    expect(within(panel).getByText('Why is this so?')).toBeInTheDocument()
    expect(await within(panel).findByText(/flat-rate pricing/, { selector: 'strong' }, { timeout: 8000 })).toBeInTheDocument()
  }, 15000)

  it('shows an error mid-answer inline with Retry', async () => {
    setFetchForTesting(mockFetch)
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: 'Explain' }, { timeout: 4000 })
    const box = screen.getByLabelText('Message the assistant')
    fireEvent.change(box, { target: { value: 'please fail now' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(await screen.findByText('The engine stopped responding (sample error).', {}, { timeout: 8000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  }, 15000)

  /** Serve the sample app, but answer every message with the given stream error. */
  function failWith(message: string, status = 200) {
    setFetchForTesting(async (url, init) => {
      if (url.includes('/messages') && init?.method === 'POST') {
        if (status !== 200) return new Response(JSON.stringify({ detail: message }), { status })
        return new Response(`data: ${JSON.stringify({ type: 'error', message })}\n\n`, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }
      return mockFetch(url, init)
    })
  }

  async function ask() {
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: 'Explain' }, { timeout: 4000 })
    const box = screen.getByLabelText('Message the assistant')
    fireEvent.change(box, { target: { value: 'hello' } })
    fireEvent.keyDown(box, { key: 'Enter' })
  }

  it('answers a "no credit" failure calmly, with the raw text only under Details', async () => {
    failWith('Provider returned error 402: this account has no credit left for openrouter')
    await ask()
    expect(await screen.findByText("This engine's account has no credit left.", {}, { timeout: 6000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose another engine' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Settings' })).toBeInTheDocument()
    const alert = screen.getByText("This engine's account has no credit left.").closest('[role="alert"]') as HTMLElement
    const details = within(alert).getByText('Details').closest('details') as HTMLElement
    expect(details).not.toHaveAttribute('open')
    // The raw provider wording is not in the main line.
    expect(within(alert).getByText("This engine's account has no credit left.").textContent).not.toMatch(/402|openrouter/i)
  }, 15000)

  it('treats an HTTP 402 reply the same way', async () => {
    failWith('Payment required', 402)
    await ask()
    expect(await screen.findByText("This engine's account has no credit left.", {}, { timeout: 6000 })).toBeInTheDocument()
  }, 15000)

  it('opens Settings and the engine list from the two actions', async () => {
    failWith('no credit')
    await ask()
    await screen.findByText("This engine's account has no credit left.", {}, { timeout: 6000 })
    const select = screen.getByLabelText('Engine') as HTMLSelectElement
    const focus = vi.spyOn(select, 'focus')
    fireEvent.click(screen.getByRole('button', { name: 'Choose another engine' }))
    expect(focus).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Open Settings' }))
    expect(window.location.hash).toBe('#/settings')
    navigate({ name: 'today' })
  }, 15000)

  it('keeps ordinary errors as they were, in the main line', async () => {
    failWith('The engine stopped responding.')
    await ask()
    expect(await screen.findByText('The engine stopped responding.', {}, { timeout: 6000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Choose another engine' })).toBeNull()
  }, 15000)

  it('preselects the first available engine when the saved one is unavailable', async () => {
    window.localStorage.setItem('radar.assist.engine', JSON.stringify({ engine: 'openai', model: 'gpt-default' }))
    setFetchForTesting(mockFetch)
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: 'Explain' }, { timeout: 4000 })
    const select = screen.getByLabelText('Engine') as HTMLSelectElement
    // The sample service marks "claude" as its default and "openai" has no key.
    expect(select.value).toBe('claude::sonnet')
  })
})
