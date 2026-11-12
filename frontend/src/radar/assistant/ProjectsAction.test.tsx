// Tests for the assistant's projects question: a tidy quick-action list (four, then "More…"),
// the "Which of my projects could this help?" action, and "File this item in vault" under its answer.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { closeClaudeDialog, getClaudeDialog } from '../claude/claudeStore'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { setFilingConfigured } from '../state/filingConfigured'
import { effectiveFiling, resetFilingState } from '../state/filingState'
import { ACTION_LABELS } from './actionLabels'
import { AssistantPanel, VISIBLE_ACTIONS } from './AssistantPanel'
import { setAssistTarget } from './assistStore'
import { resetConversations } from './useThread'

beforeEach(() => {
  resetMockState()
  resetFilingState()
  // These tests are about an install where filing is set up.
  setFilingConfigured(true)
  resetConversations()
  clearResourceCache()
  window.localStorage.clear()
  setFetchForTesting(mockFetch)
})

afterEach(() => {
  cleanup()
  closeClaudeDialog()
  setFetchForTesting(null)
  setAssistTarget(null)
})

describe('quick actions', () => {
  it('shows four actions and puts the rest behind "More…"', async () => {
    setAssistTarget({ kind: 'item', id: 101, title: 'Sample' })
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: ACTION_LABELS.explain }, { timeout: 4000 })
    expect(VISIBLE_ACTIONS).toBe(4)
    for (const action of ['explain', 'relevance', 'colleagues', 'linkedin'] as const) {
      expect(screen.getByRole('button', { name: ACTION_LABELS[action] })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: ACTION_LABELS.blog })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: ACTION_LABELS.projects })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'More…' }))
    expect(screen.getByRole('button', { name: ACTION_LABELS.blog })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which of my projects could this help?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'More…' })).not.toBeInTheDocument()
  })

  it('leaves the projects question out of Today, which is about the whole brief', async () => {
    setAssistTarget({ kind: 'brief', day: '2026-11-12' })
    render(<AssistantPanel surface="today" />)
    await screen.findByRole('button', { name: ACTION_LABELS.explain }, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: 'More…' }))
    expect(screen.queryByRole('button', { name: ACTION_LABELS.projects })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: ACTION_LABELS.blog })).toBeInTheDocument()
  })
})

describe('Which of my projects could this help?', () => {
  it('answers, then offers "File this item in vault", which queues the item and opens nothing', async () => {
    setAssistTarget({ kind: 'item', id: 101, title: 'Sample' })
    render(<AssistantPanel surface="reader" />)
    await screen.findByRole('button', { name: ACTION_LABELS.explain }, { timeout: 4000 })
    fireEvent.click(screen.getByRole('button', { name: 'More…' }))
    fireEvent.click(screen.getByRole('button', { name: 'Which of my projects could this help?' }))
    const panel = screen.getByRole('complementary', { name: 'Assistant' })
    const file = await within(panel).findByRole('button', { name: 'File this item in vault' }, { timeout: 9000 })
    expect(within(panel).getByText(/Nothing has been filed/)).toBeInTheDocument()
    act(() => file.click())
    await waitFor(() => expect(effectiveFiling(101, null)).toBe('waiting'))
    expect(getClaudeDialog()).toBeNull()
  }, 20000)

  it('offers "File this item in vault" only under an answer to the projects question', async () => {
    setAssistTarget({ kind: 'item', id: 101, title: 'Sample' })
    render(<AssistantPanel surface="reader" />)
    fireEvent.click(await screen.findByRole('button', { name: ACTION_LABELS.explain }, { timeout: 4000 }))
    await screen.findByRole('button', { name: 'Copy' }, { timeout: 9000 })
    expect(screen.queryByRole('button', { name: 'File this item in vault' })).not.toBeInTheDocument()
  }, 20000)
})
