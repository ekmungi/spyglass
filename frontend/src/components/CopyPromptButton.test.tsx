// Tests for the copy fallback shown when the Claude desktop app cannot be opened.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CopyPromptButton } from './CopyPromptButton'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('CopyPromptButton', () => {
  it('copies the whole prompt, says so, then goes away', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const onDone = vi.fn()
    render(<CopyPromptButton prompt={'Compare\n\nCards: #1 "A"'} onDone={onDone} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy prompt' }))
    })
    expect(writeText).toHaveBeenCalledWith('Compare\n\nCards: #1 "A"')
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1500)
    })
    expect(onDone).toHaveBeenCalled()
  })

  it('says so when the clipboard refuses', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn(async () => Promise.reject(new Error('no'))) } })
    render(<CopyPromptButton prompt="p" onDone={() => {}} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy prompt' }))
    })
    expect(screen.getByRole('button', { name: 'Copy failed' })).toBeInTheDocument()
  })
})
